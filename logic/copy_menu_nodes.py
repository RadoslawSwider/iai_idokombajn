
import requests
import math
from collections import defaultdict
from typing import Generator, Any

API_ENDPOINT_PATH = "/api/admin/v7/menu/menu"
BATCH_SIZE = 100

def get_source_menu(base_url: str, api_key: str, shop_id: int, menu_id: int, lang_id: str) -> list[dict[str, Any]]:
    """Pobiera pełną strukturę menu ze sklepu źródłowego."""
    menu_api_url = f"{base_url}{API_ENDPOINT_PATH}"
    params = {
        'shop_id': shop_id,
        'menu_id': menu_id,
        'lang_id': lang_id
    }
    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key
    }
    
    try:
        response = requests.get(menu_api_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("result"):
            raise RuntimeError("Odpowiedź API nie zawiera danych menu ('result' jest pusty).")
        return data['result']
    except requests.exceptions.HTTPError as errh:
        raise RuntimeError(f"BŁĄD HTTP: {errh}\nURL: {response.request.url}\nTreść: {response.text}") from errh
    except requests.exceptions.RequestException as err:
        raise RuntimeError(f"BŁĄD krytyczny podczas pobierania menu: {err}") from err

def create_menu_items_batch(base_url: str, api_key: str, shop_id: int, menu_id: int, items_to_create: list[dict[str, Any]], parent_id: int | None = None) -> list[int | None]:
    """Tworzy wiele elementów menu w jednym zapytaniu (w paczce)."""
    menu_api_url = f"{base_url}{API_ENDPOINT_PATH}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    
    menu_list_payload = []
    for item_data in items_to_create:
        lang_data_to_send = item_data['lang_data'][0]
        payload_item = {
            "shop_id": shop_id,
            "menu_id": menu_id,
            "lang_data": [lang_data_to_send]
        }
        if parent_id:
            payload_item["parent_id"] = parent_id
        menu_list_payload.append(payload_item)

    full_payload = {"menu_list": menu_list_payload}
    
    try:
        response = requests.post(menu_api_url, json=full_payload, headers=headers)
        response.raise_for_status()
        results = response.json().get('result', [])
        
        if len(results) != len(items_to_create):
            raise RuntimeError(f"Niezgodność liczby elementów wysłanych ({len(items_to_create)}) i otrzymanych ({len(results)}).")

        new_ids = []
        for i, result in enumerate(results):
            if result.get("faultCode", 0) != 0:
                item_name = items_to_create[i]['lang_data'][0]['name']
                # Zwracamy błąd jako None, obsługa w pętli wyżej
                new_ids.append(None)
            else:
                new_ids.append(result['item_id'])
        return new_ids

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Błąd requesta podczas tworzenia paczki: {e}\nTreść: {e.response.text}") from e

def run_copy_menu_nodes(base_url: str, api_key: str, source_shop_id: int, source_menu_id: int, dest_shop_id: int, dest_menu_id: int, lang_id: str) -> Generator[str, None, None]:
    """Główna funkcja orkiestrująca proces replikacji z użyciem paczek."""
    yield f"Krok 1: Pobieranie menu ze sklepu źródłowego (shop_id: {source_shop_id}, menu_id: {source_menu_id}, lang: {lang_id})..."
    try:
        source_items = get_source_menu(base_url, api_key, source_shop_id, source_menu_id, lang_id)
        yield f"Pobrano {len(source_items)} elementów menu."
    except RuntimeError as e:
        yield f"BŁĄD: {e}"
        return

    source_to_dest_id_map = {}
    nodes_by_parent = defaultdict(list)
    all_item_ids = set(item['item_id'] for item in source_items)
    
    for item in source_items:
        nodes_by_parent[item['parent_id']].append(item)

    root_items_parents = [pid for pid in nodes_by_parent if pid not in all_item_ids]
    if not root_items_parents:
        yield "BŁĄD: Nie znaleziono głównych elementów menu (korzeni)."
        return

    yield f"Krok 2: Znaleziono {len(root_items_parents)} rodziców dla głównych elementów. Rozpoczynanie replikacji w paczkach..."

    def process_nodes_in_batches(source_parent_id: int, dest_parent_id: int | None = None) -> Generator[str, None, None]:
        children_to_create = nodes_by_parent.get(source_parent_id, [])
        if not children_to_create:
            return

        sorted_children = sorted(children_to_create, key=lambda x: x['lang_data'][0]['priority'])
        parent_info = "jako elementy główne" if not dest_parent_id else f"pod rodzicem o nowym ID: {dest_parent_id}"
        yield f"-> Znaleziono {len(sorted_children)} elementów {parent_info}. Dzielenie na paczki po {BATCH_SIZE}..."
        
        for i in range(0, len(sorted_children), BATCH_SIZE):
            batch = sorted_children[i:i + BATCH_SIZE]
            
            yield f"    -> Przetwarzanie paczki {math.ceil((i+1)/BATCH_SIZE)}/{math.ceil(len(sorted_children)/BATCH_SIZE)} (elementy od {i+1} do {i+len(batch)})..."
            
            try:
                new_ids = create_menu_items_batch(
                    base_url, api_key, dest_shop_id, dest_menu_id, batch, parent_id=dest_parent_id
                )
            except RuntimeError as e:
                yield f"    ...BŁĄD KRYTYCZNY! Nie udało się przetworzyć paczki: {e}. Pomijanie."
                continue

            for original_item, new_id in zip(batch, new_ids):
                if new_id:
                    source_item_id = original_item['item_id']
                    source_to_dest_id_map[source_item_id] = new_id
                    yield from process_nodes_in_batches(source_item_id, new_id)
                else:
                    item_name = original_item['lang_data'][0]['name']
                    yield f"    ...Pominięto tworzenie dzieci dla '{item_name}' z powodu błędu tworzenia."

    for root_parent_id in root_items_parents:
        yield from process_nodes_in_batches(root_parent_id, None)

    yield "\nKrok 3: Zakończono replikację menu!"
