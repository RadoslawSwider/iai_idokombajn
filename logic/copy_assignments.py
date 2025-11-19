# logic/copy_assignments.py

import csv
from collections import defaultdict
from typing import Generator, Dict, List

# Assuming these functions are available from other logic files
# A real implementation might put get_menu_data in a shared api_utils.py
from logic.pinner import run_pinner_by_id
import requests # Required for the standalone get_menu_data

def get_menu_data(base_url: str, api_key: str, shop_id: str, menu_id: str, lang_id: str) -> List[Dict]:
    """Fetches menu data for a given shop, menu, and language."""
    url = f"{base_url.rstrip('/')}/api/admin/v7/menu/menu?shop_id={shop_id}&menu_id={menu_id}&lang_id={lang_id}"
    headers = {"accept": "application/json", "X-API-KEY": api_key}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("result", [])
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Błąd API podczas pobierania menu: {e}") from e

def _gather_all_products_by_path(shop_id: str, menu_id: str) -> Dict[str, List[int]]:
    """
    Reads 'produkty_menu_final.csv' and groups product IDs by their category path (menuItemTextId)
    for a specific shop and menu.
    """
    products_by_path = defaultdict(list)
    try:
        with open("produkty_menu_final.csv", 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get('shopId') == shop_id and row.get('menuId') == menu_id:
                    path = row.get('menuItemTextId')
                    product_id = row.get('productId')
                    if path and product_id:
                        products_by_path[path].append(int(product_id))
    except FileNotFoundError:
        raise FileNotFoundError("Plik 'produkty_menu_final.csv' nie został znaleziony. Uruchom najpierw moduł 'Pobierz informacje o elementach menu'.")
    return products_by_path

def run_copy_all_assignments(
    base_url: str,
    api_key: str,
    source_shop_id: str,
    source_menu_id: str,
    target_shop_id: str,
    target_menu_id: str,
    target_lang_id: str,
    progress_callback=None,
    **pinner_kwargs
) -> Generator[str, None, None]:
    """
    Orchestrates the process of copying all product assignments from a source menu to a target menu.
    """
    try:
        # 1. Get all assignments from CSV for the source menu
        yield "Krok 1/3: Zbieranie wszystkich przypisań z menu źródłowego..."
        products_by_path = _gather_all_products_by_path(source_shop_id, source_menu_id)
        if not products_by_path:
            yield "Nie znaleziono żadnych produktów w menu źródłowym lub plik CSV jest pusty. Zakończono."
            return
        yield f"Znaleziono produkty w {len(products_by_path)} unikalnych kategoriach."

        # 2. Get target menu structure and create a path -> id map
        yield "\nKrok 2/3: Pobieranie struktury menu docelowego i tworzenie mapy ścieżek..."
        target_menu_items = get_menu_data(base_url, api_key, target_shop_id, target_menu_id, target_lang_id)
        if not target_menu_items:
            yield "BŁĄD: Nie udało się pobrać struktury menu docelowego lub jest ono puste. Zakończono."
            return
            
        target_path_to_id_map = {
            item['lang_data'][0].get('item_textid'): item['item_id']
            for item in target_menu_items if item.get('lang_data') and item['lang_data'][0].get('item_textid')
        }
        yield f"Stworzono mapę dla {len(target_path_to_id_map)} kategorii w menu docelowym."

        # 3. Iterate through source categories and pin products to the target
        yield "\nKrok 3/3: Rozpoczynanie procesu przypinania dla każdej kategorii..."
        total_categories = len(products_by_path)
        processed_categories = 0
        
        for path, product_ids in products_by_path.items():
            processed_categories += 1
            yield f"\n--- Przetwarzanie kategorii {processed_categories}/{total_categories}: '{path}' ---"
            
            if path not in target_path_to_id_map:
                yield f"OSTRZEŻENIE: Nie znaleziono odpowiednika kategorii '{path}' w menu docelowym. Pomijanie {len(product_ids)} produktów."
                continue
            
            target_node_id = target_path_to_id_map[path]
            yield f"Znaleziono odpowiednik w menu docelowym (ID węzła: {target_node_id}). Znaleziono {len(product_ids)} produktów do przypisania."

            # Create a sub-generator for the pinner and yield from it
            pinner_task = run_pinner_by_id(
                base_url=base_url,
                api_key=api_key,
                product_ids=product_ids,
                target_shop_id=int(target_shop_id),
                target_menu_id=int(target_menu_id),
                target_node_id=target_node_id,
                progress_callback=progress_callback,
                **pinner_kwargs
            )
            yield from pinner_task

    except Exception as e:
        import traceback
        yield f"Wystąpił krytyczny błąd w procesie kopiowania: {e}\n{traceback.format_exc()}"

    yield "\n--- Zakończono proces kopiowania wszystkich przypisań. ---"
