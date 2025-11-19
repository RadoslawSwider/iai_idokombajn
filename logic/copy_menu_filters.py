
import requests
import time
from typing import Generator, Any

API_ENDPOINT_PATH = "/api/admin/v7/menu/filter"

def get_menu_filters(base_url: str, api_key: str, shop_id: int, menu_id: int, menu_node_id: int, lang_id: str) -> dict[str, Any]:
    """Pobiera filtry dla danego węzła menu."""
    api_url = f"{base_url}{API_ENDPOINT_PATH}"
    params = {
        'shopId': shop_id,
        'productMenuTreeId': menu_id,
        'productMenuNodeId': menu_node_id,
        'languageId': lang_id
    }
    headers = {
        "accept": "application/json",
        "X-API-KEY": api_key
    }
    
    try:
        time.sleep(0.5) # Opóźnienie, aby uniknąć bana
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("result"):
            raise RuntimeError("Odpowiedź API nie zawiera danych filtrów ('result' jest pusty).")
        return data['result']['menuFilters']
    except requests.exceptions.HTTPError as errh:
        raise RuntimeError(f"BŁĄD HTTP podczas pobierania filtrów: {errh}\nURL: {response.request.url}\nTreść: {response.text}") from errh
    except requests.exceptions.RequestException as err:
        raise RuntimeError(f"BŁĄD krytyczny podczas pobierania filtrów: {err}") from err

def set_menu_filters(base_url: str, api_key: str, shop_id: int, menu_id: int, menu_node_id: int, lang_id: str, active_filters: list[dict[str, Any]]) -> None:
    """Ustawia aktywne filtry dla danego węzła menu."""
    api_url = f"{base_url}{API_ENDPOINT_PATH}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    # Zgodnie z dostarczonym przykładem, payload jest zagnieżdżony w obiekcie "params"
    payload = {
        "params": {
            "shopId": shop_id,
            "languageId": lang_id,
            "productMenuTreeId": menu_id,
            "menuFiltersActive": active_filters,
            "productMenuNodeId": menu_node_id
        }
    }
    
    try:
        time.sleep(0.5) # Opóźnienie, aby uniknąć bana
        response = requests.put(api_url, json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as errh:
        error_details = f"BŁĄD HTTP podczas ustawiania filtrów: {errh}"
        try:
            error_details += f"\nURL: {response.request.url}"
            error_details += f"\nPayload: {response.request.body}"
            error_details += f"\nTreść odpowiedzi: {response.text}"
        except Exception:
            pass
        raise RuntimeError(error_details) from errh
    except requests.exceptions.RequestException as err:
        raise RuntimeError(f"BŁĄD krytyczny podczas ustawiania filtrów: {err}") from err

def run_copy_filters_for_node(
    base_url: str, 
    api_key: str, 
    source_shop_id: int, 
    source_menu_id: int, 
    source_node_id: int, 
    dest_shop_id: int, 
    dest_menu_id: int, 
    dest_node_id: int, 
    source_lang_id: str,
    dest_lang_id: str
) -> Generator[str, None, None]:
    """Kopiuje ustawienia filtrów z jednego węzła do drugiego."""
    yield f"    -> Rozpoczynanie kopiowania filtrów dla węzła {source_node_id} -> {dest_node_id}..."
    
    try:
        # 1. Pobierz filtry ze źródła
        source_filters = get_menu_filters(base_url, api_key, source_shop_id, source_menu_id, source_node_id, source_lang_id)
        source_active_filters = source_filters.get('menuFiltersActive', {})
        
        if not source_active_filters:
            yield f"    -> Węzeł źródłowy {source_node_id} nie ma aktywnych filtrów. Pomijanie."
            return
            
        yield f"    -> Znaleziono {len(source_active_filters)} aktywnych filtrów w źródle (język: {source_lang_id}). Dopasowywanie po ID z zachowaniem kolejności."

        # 2. Pobierz wszystkie filtry z celu
        dest_filters = get_menu_filters(base_url, api_key, dest_shop_id, dest_menu_id, dest_node_id, dest_lang_id)
        all_dest_filters = {**dest_filters.get('menuFiltersActive', {}), **dest_filters.get('menuFiltersNonActive', {})}
        
        if not all_dest_filters:
            yield f"    -> OSTRZEŻENIE: Nie znaleziono żadnych dostępnych filtrów w węźle docelowym {dest_node_id} (język: {dest_lang_id})."
            return

        # 3. Znajdź pasujące filtry w celu po ID, zachowaj kolejność i skopiuj ustawienia
        dest_filters_to_set = []
        for filter_id, source_data in source_active_filters.items():
            if filter_id in all_dest_filters:
                dest_data = all_dest_filters[filter_id]
                dest_filters_to_set.append({
                    "menuFilterId": dest_data['menuFilterId'],
                    "menuFilterName": dest_data['menuFilterName'],
                    # Przenosimy ustawienia ze źródła, jeśli istnieją, z domyślnymi wartościami
                    "menuFilterDisplay": source_data.get("menuFilterDisplay", "name"),
                    "menuFilterValueSort": source_data.get("menuFilterValueSort", "y"),
                    "menuFilterDefaultEnabled": source_data.get("menuFilterDefaultEnabled", "n")
                })
        
        yield f"    -> Znaleziono {len(dest_filters_to_set)} pasujących filtrów w celu."

        # 4. Ustaw filtry w celu
        if dest_filters_to_set:
            set_menu_filters(base_url, api_key, dest_shop_id, dest_menu_id, dest_node_id, dest_lang_id, dest_filters_to_set)
            yield f"    -> Sukces: Ustawiono {len(dest_filters_to_set)} filtrów w węźle docelowym {dest_node_id} (język: {dest_lang_id})."
        else:
            yield f"    -> Informacja: Nie znaleziono pasujących filtrów do ustawienia w węźle docelowym."

    except RuntimeError as e:
        yield f"    -> BŁĄD podczas kopiowania filtrów dla węzła {source_node_id}: {e}"
