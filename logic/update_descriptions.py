
import requests
import json
from typing import Generator, Any

API_ENDPOINT_PATH = "/api/admin/v7/menu/menu"

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

def update_menu_descriptions(base_url: str, api_key: str, payload_list: list[dict[str, Any]]) -> Generator[str, None, None]:
    """Wysyła zaktualizowane opisy do API w paczkach po 100."""
    if not payload_list:
        yield "ℹ️ Brak zmian do wprowadzenia. Opisy są już zsynchronizowane."
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

def run_update_descriptions(base_url: str, api_key: str, source_shop_id: str, source_menu_id: str, dest_shop_id: str, dest_menu_id: str, dest_lang_id: str, progress_callback=None) -> Generator[str, None, None]:
    """Główna funkcja orkiestrująca działanie."""
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

    source_description_map = {}
    for item in source_menu_items:
        if item.get("lang_data"):
            lang_item = item["lang_data"][0]
            name = lang_item.get("name")
            if name:
                source_description_map[name] = {
                    "desc": lang_item.get("description", ""),
                    "desc_bottom": lang_item.get("description_bottom", "")
                }
    
    yield f"🗺️ Stworzono mapę opisów na podstawie {len(source_description_map)} unikalnych nazw."

    yield f"--- Pobieranie danych ze sklepu docelowego (ID: {dest_shop_id}, Menu: {dest_menu_id}, Język: {SOURCE_LANG_ID}) ---"
    try:
        dest_menu_items = get_menu_data(base_url, api_key, dest_shop_id, dest_menu_id, SOURCE_LANG_ID)
        if not dest_menu_items:
            yield f"⚠️ Nie znaleziono pozycji menu dla sklepu docelowego."
            return
        yield f"✅ Pomyślnie pobrano {len(dest_menu_items)} pozycji z celu."
    except RuntimeError as e:
        yield str(e)
        return

    updates_to_make = []
    yield "\n--- Porównywanie opisów i przygotowywanie zmian ---"
    for item in dest_menu_items:
        if item.get("lang_data"):
            dest_lang_item = item["lang_data"][0]
            dest_name = dest_lang_item.get("name")
            dest_item_id = item.get("item_id")
            
            if dest_name in source_description_map:
                source_data = source_description_map[dest_name]
                current_desc = dest_lang_item.get("description", "")
                current_desc_bottom = dest_lang_item.get("description_bottom", "")

                if source_data["desc"] != current_desc or source_data["desc_bottom"] != current_desc_bottom:
                    yield f"➡️ Znaleziono różnicę w opisach dla '{dest_name}'. Przygotowuję aktualizację dla języka '{dest_lang_id}'."
                    update_item = {
                        "shop_id": int(dest_shop_id),
                        "menu_id": int(dest_menu_id),
                        "item_id": str(dest_item_id),
                        "lang_data": [{
                            "lang_id": dest_lang_id,
                            "description": source_data["desc"],
                            "description_bottom": source_data["desc_bottom"]
                        }]
                    }
                    updates_to_make.append(update_item)
            else:
                yield f"🤔 Ostrzeżenie: Pozycja '{dest_name}' (ID: {dest_item_id}) istnieje w menu docelowym, ale nie znaleziono jej w źródłowym. Zostanie pominięta."

    yield "\n--- Wysyłanie aktualizacji do API ---"
    yield from update_menu_descriptions(base_url, api_key, updates_to_make)
