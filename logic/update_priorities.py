import requests
import json
from typing import Generator, Any, Tuple, Dict

API_ENDPOINT_PATH = "/api/admin/v7/menu/menu"

def _build_path_and_priority_maps(items: list[dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    Buduje mapę ścieżek dla każdego elementu menu oraz mapę priorytetów opartą na tych ścieżkach.
    Ścieżka jest tworzona przez połączenie nazw rodziców, np. "Rodzic/Dziecko/Wnuk".
    """
    items_by_id = {item['item_id']: item for item in items if 'item_id' in item}
    
    # Cache dla zbudowanych ścieżek, aby unikać wielokrotnego obliczania
    path_cache = {}

    def get_path(item_id: str) -> str:
        """Rekurencyjnie buduje pełną ścieżkę dla danego item_id."""
        if item_id in path_cache:
            return path_cache[item_id]
        
        item = items_by_id.get(item_id)
        if not item:
            return "" # Powinno się nie zdarzyć w spójnych danych

        # Zakładamy, że lang_data istnieje i ma co najmniej jeden element
        name = item.get('lang_data', [{}])[0].get('name', '')
        parent_id = item.get('parent_id')

        if parent_id and parent_id != "0":
            parent_path = get_path(parent_id)
            path = f"{parent_path}/{name}" if parent_path else name
        else:
            path = name
        
        path_cache[item_id] = path
        return path

    path_to_priority_map = {}
    for item in items:
        item_id = item.get('item_id')
        if not item_id:
            continue
            
        path = get_path(item_id)
        priority = item.get('lang_data', [{}])[0].get('priority')
        
        if path and priority is not None:
            path_to_priority_map[path] = priority
            
    # Druga mapa jest potrzebna do znalezienia item_id na podstawie ścieżki w menu docelowym
    path_to_item_id_map = {get_path(item['item_id']): item['item_id'] for item in items if 'item_id' in item}

    return path_to_item_id_map, path_to_priority_map


def get_menu_data(base_url: str, api_key: str, shop_id: str, menu_id: str, lang_id: str) -> dict[str, Any] | None:
    """Pobiera dane o menu dla danego sklepu, ID menu i języka."""
    url = f"{base_url}{API_ENDPOINT_PATH}?shop_id={shop_id}&menu_id={menu_id}&lang_id={lang_id}"
    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "result" in data and data["result"]:
            return data["result"]
        else:
            return None
            
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Błąd podczas pobierania danych dla sklepu ID: {shop_id}. Błąd: {e}") from e

def update_menu_priorities(base_url: str, api_key: str, payload_list: list[dict[str, Any]]) -> Generator[str, None, None]:
    """Wysyła zaktualizowane priorytety do API w paczkach po 100."""
    if not payload_list:
        yield "ℹ️ Brak zmian do wprowadzenia. Priorytety są już zsynchronizowane."
        return

    url = f"{base_url}{API_ENDPOINT_PATH}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    
    total_items = len(payload_list)
    batch_size = 100

    for i in range(0, total_items, batch_size):
        batch = payload_list[i:i + batch_size]
        payload = {"menu_list": batch}
        
        yield f"🚀 Wysyłanie paczki {i//batch_size + 1}/{(total_items + batch_size - 1)//batch_size} ({len(batch)} pozycji)..."
        
        try:
            response = requests.put(url, json=payload, headers=headers)
            response.raise_for_status()
            yield f"✅ Paczka {i//batch_size + 1} zaktualizowana pomyślnie!"

        except requests.exceptions.RequestException as e:
            error_message = f"❌ Błąd podczas aktualizacji paczki {i//batch_size + 1}. Błąd: {e}"
            if hasattr(e, 'response') and e.response is not None:
                error_message += f"\nTreść odpowiedzi błędu: {e.response.text}"
            yield error_message

def run_update_priorities(base_url: str, api_key: str, source_shop_id: str, source_menu_id: str, dest_shop_id: str, dest_menu_id: str, dest_lang_id: str, progress_callback=None) -> Generator[str, None, None]:
    """Główna funkcja orkiestrująca, która używa pełnych ścieżek do porównywania węzłów."""
    SOURCE_LANG_ID = "pol"

    yield f"--- Pobieranie danych ze sklepu źródłowego (ID: {source_shop_id}, Menu: {source_menu_id}, Język: {SOURCE_LANG_ID}) ---"
    try:
        source_menu_items = get_menu_data(base_url, api_key, source_shop_id, source_menu_id, SOURCE_LANG_ID)
        if not source_menu_items:
            yield f"⚠️ Nie znaleziono pozycji menu dla sklepu źródłowego."
            return
        yield f"✅ Pomyślnie pobrano {len(source_menu_items)} pozycji ze źródła."
    except RuntimeError as e:
        yield str(e)
        return

    _, source_path_to_priority_map = _build_path_and_priority_maps(source_menu_items)
    yield f"🗺️ Stworzono mapę priorytetów dla źródła na podstawie {len(source_path_to_priority_map)} unikalnych ścieżek."

    yield f"--- Pobieranie danych referencyjnych z celu (Język: {SOURCE_LANG_ID}) ---"
    try:
        dest_menu_items_pol = get_menu_data(base_url, api_key, dest_shop_id, dest_menu_id, SOURCE_LANG_ID)
        if not dest_menu_items_pol:
            yield f"⚠️ Nie znaleziono pozycji menu dla sklepu docelowego w języku '{SOURCE_LANG_ID}'."
            return
        yield f"✅ Pomyślnie pobrano {len(dest_menu_items_pol)} pozycji referencyjnych z celu."
    except RuntimeError as e:
        yield str(e)
        return
    
    dest_path_to_item_id_map, _ = _build_path_and_priority_maps(dest_menu_items_pol)
    yield f"🗺️ Stworzono mapę ścieżek do ID dla celu na podstawie {len(dest_path_to_item_id_map)} unikalnych ścieżek."

    yield f"--- Pobieranie aktualnych priorytetów z celu (Język: {dest_lang_id}) ---"
    try:
        dest_menu_items_lang = get_menu_data(base_url, api_key, dest_shop_id, dest_menu_id, dest_lang_id)
        if not dest_menu_items_lang:
            yield f"⚠️ Nie znaleziono pozycji menu dla sklepu docelowego w języku '{dest_lang_id}'. Zmiany mogą nie zostać zastosowane."
            dest_menu_items_lang = []
    except RuntimeError as e:
        yield str(e)
        return

    dest_item_id_to_priority_map = {
        item['item_id']: item.get('lang_data', [{}])[0].get('priority')
        for item in dest_menu_items_lang
        if 'item_id' in item and item.get('lang_data')
    }
    yield f"🗺️ Stworzono mapę aktualnych priorytetów dla {len(dest_item_id_to_priority_map)} pozycji w języku '{dest_lang_id}'."


    updates_to_make = []
    yield "\n--- Porównywanie priorytetów i przygotowywanie zmian ---"
    
    for path, dest_item_id in dest_path_to_item_id_map.items():
        if path in source_path_to_priority_map:
            source_priority = source_path_to_priority_map[path]
            current_priority = dest_item_id_to_priority_map.get(dest_item_id)
            
            if current_priority != source_priority:
                yield f"➡️ Znaleziono różnicę dla ścieżki '{path}': jest {current_priority}, powinno być {source_priority}. Przygotowuję aktualizację."
                update_item = {
                    "shop_id": int(dest_shop_id),
                    "menu_id": int(dest_menu_id),
                    "item_id": str(dest_item_id),
                    "lang_data": [{
                        "lang_id": dest_lang_id,
                        "priority": source_priority
                    }]
                }
                updates_to_make.append(update_item)
        else:
            yield f"🤔 Ostrzeżenie: Ścieżka '{path}' (ID: {dest_item_id}) istnieje w menu docelowym (PL), ale nie znaleziono jej w źródłowym. Zostanie pominięta."

    yield "\n--- Wysyłanie aktualizacji do API ---"
    yield from update_menu_priorities(base_url, api_key, updates_to_make)