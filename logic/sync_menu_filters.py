from typing import Generator, Any, Dict
from collections import defaultdict

# Importuj funkcje z istniejących modułów, aby uniknąć duplikacji kodu
from .copy_menu_nodes import get_source_menu 
from .copy_menu_filters import run_copy_filters_for_node

def build_node_path_map(items: list[dict[str, Any]]) -> Dict[str, int]:
    """Tworzy mapowanie: 'pełna/ścieżka/do/węzła' -> item_id."""
    
    # Słownik przechowujący item_id -> dane elementu
    items_by_id = {item['item_id']: item for item in items}
    # Słownik przechowujący parent_id -> lista dzieci
    children_by_parent = defaultdict(list)
    for item in items:
        children_by_parent[item['parent_id']].append(item)

    # Słownik do przechowywania wygenerowanych ścieżek
    path_map = {}
    # Słownik do cachowania ścieżek, aby uniknąć wielokrotnego obliczania
    memo = {}

    def get_path(item_id: int) -> str:
        """Rekurencyjnie buduje ścieżkę dla danego item_id."""
        if item_id in memo:
            return memo[item_id]
        
        item = items_by_id.get(item_id)
        if not item:
            return "" # Powinno się nie zdarzyć w poprawnych danych

        # Pobierz nazwę z pierwszego elementu lang_data
        name = item['lang_data'][0]['name']
        parent_id = item['parent_id']

        # Jeśli element nie jest w głównym korzeniu, dołącz ścieżkę rodzica
        if parent_id in items_by_id:
            path = get_path(parent_id) + "/" + name
        else:
            path = name
        
        memo[item_id] = path
        return path

    # Wygeneruj ścieżki dla wszystkich elementów
    for item in items:
        item_id = item['item_id']
        if item_id not in path_map:
            path_map[get_path(item_id)] = item_id
            
    return path_map

def run_sync_menu_filters(
    base_url: str, 
    api_key: str, 
    source_shop_id: int, 
    source_menu_id: int, 
    dest_shop_id: int, 
    dest_menu_id: int, 
    lang_id: str,
    dest_lang_id: str = None,
    progress_callback=None
) -> Generator[str, None, None]:
    """Orkiestruje proces synchronizacji filtrów między dwoma menu."""

    if not dest_lang_id:
        dest_lang_id = lang_id
        yield f"INFO: Język docelowy nie został podany, używam języka źródłowego: {lang_id}"
    
    yield "Krok 1: Pobieranie struktury menu źródłowego..."
    try:
        source_items = get_source_menu(base_url, api_key, source_shop_id, source_menu_id, lang_id)
        yield f"Pobrano {len(source_items)} węzłów z menu źródłowego (język: {lang_id})."
    except Exception as e:
        yield f"BŁĄD KRYTYCZNY: Nie udało się pobrać menu źródłowego: {e}"
        return

    yield "Krok 2: Pobieranie struktury menu docelowego..."
    try:
        dest_items = get_source_menu(base_url, api_key, dest_shop_id, dest_menu_id, dest_lang_id)
        yield f"Pobrano {len(dest_items)} węzłów z menu docelowego (język: {dest_lang_id})."
    except Exception as e:
        yield f"BŁĄD KRYTYCZNY: Nie udało się pobrać menu docelowego: {e}"
        return

    yield "Krok 3: Budowanie mapy ścieżek dla obu menu..."
    source_path_map = build_node_path_map(source_items)
    dest_path_map = build_node_path_map(dest_items)
    yield f"Zmapowano {len(source_path_map)} ścieżek w menu źródłowym i {len(dest_path_map)} w docelowym."

    yield "\nKrok 4: Rozpoczynanie synchronizacji filtrów dla pasujących węzłów..."
    
    matched_nodes = 0
    for path, source_node_id in source_path_map.items():
        if path in dest_path_map:
            matched_nodes += 1
            dest_node_id = dest_path_map[path]
            yield f"\n-> Znaleziono dopasowanie dla ścieżki '{path}':"
            yield f"   Źródło Node ID: {source_node_id}, Cel Node ID: {dest_node_id}" 
            
            # Użyj istniejącej logiki do skopiowania filtrów dla tej pary węzłów
            yield from run_copy_filters_for_node(
                base_url=base_url,
                api_key=api_key,
                source_shop_id=source_shop_id,
                source_menu_id=source_menu_id,
                source_node_id=source_node_id,
                dest_shop_id=dest_shop_id,
                dest_menu_id=dest_menu_id,
                dest_node_id=dest_node_id,
                source_lang_id=lang_id,
                dest_lang_id=dest_lang_id
            )
    
    if matched_nodes == 0:
        yield "\nOSTRZEŻENIE: Nie znaleziono żadnych pasujących węzłów między menu źródłowym a docelowym."
    else:
        yield f"\nPrzeskanowano i zsynchronizowano filtry dla {matched_nodes} pasujących węzłów."

    yield "\nKrok 5: Zakończono synchronizację filtrów!"
