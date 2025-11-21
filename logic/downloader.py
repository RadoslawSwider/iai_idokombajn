import requests
import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ENDPOINT = "api/admin/v7/products/products/search"
OUTPUT_FILENAME = "produkty_menu_final.csv"

def post_with_retry(full_url, json_payload, headers, timeout=30):
    """Wysyła zapytanie POST z logiką ponawiania."""
    for attempt in range(10):
        try:
            response = requests.post(full_url, json=json_payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt < 9:
                time.sleep(60)
            else:
                raise e

def process_products(products):
    """Przetwarza listę produktów i zwraca wyekstrahowane dane."""
    product_data = []
    for product in products:
        product_id = product.get("productId")
        if "productMenu" in product and product["productMenu"]:
            for menu_item in product["productMenu"]:
                shop_id = menu_item.get("shopId")
                menu_id = menu_item.get("menuId")
                menu_descriptions = menu_item.get("menuItemDescriptionsLangData", [])
                if not menu_descriptions:
                    continue
                
                target_description = None
                # Szukaj opisu po polsku
                for lang_data in menu_descriptions:
                    if lang_data.get("langId") == "pol":
                        target_description = lang_data
                        break
                
                # Jeśli nie ma polskiego, weź pierwszy z listy
                if not target_description and menu_descriptions:
                    target_description = menu_descriptions[0]

                if target_description:
                    extracted_row = {
                        "productId": product_id,
                        "shopId": shop_id,
                        "menuId": menu_id,
                        "menuItemTextId": target_description.get("menuItemTextId")
                    }
                    product_data.append(extracted_row)
    return product_data

def fetch_page(page_num, full_url, headers):
    """Pobiera i przetwarza pojedynczą stronę danych."""
    payload = {"params": {"returnProducts": "active", "resultsPage": page_num}}
    try:
        response = post_with_retry(full_url, json_payload=payload, headers=headers)
        data = response.json()
        return process_products(data.get("results", []))
    except requests.exceptions.RequestException as e:
        # Zwracamy błąd, aby główna pętla mogła go obsłużyć
        return f"Błąd (strona {page_num + 1}): {e}"
    except ValueError:
        # Zwracamy błąd, aby główna pętla mogła go obsłużyć
        return f"Błąd JSON (strona {page_num + 1})"

def fetch_and_process_data(full_url, headers):
    all_products_data = []
    yield "Pobieranie pierwszej strony, aby ustalić liczbę wszystkich stron..."
    
    try:
        # Pobranie pierwszej strony, aby poznać metadane paginacji
        response = post_with_retry(full_url, json_payload={"params": {"returnProducts": "active", "resultsPage": 0}}, headers=headers)
        first_page_data = response.json()
    except requests.exceptions.RequestException as e:
        yield f"Krytyczny błąd: Nie udało się pobrać pierwszej strony danych po 10 próbach. {e}"
        yield "Sprawdź, czy podałeś poprawny Base URL i czy serwer jest dostępny."
        return
    except ValueError:
        yield f"Krytyczny błąd: Nie udało się zdekodować odpowiedzi JSON. Sprawdź poprawność klucza API."
        yield f"Odpowiedź serwera: {response.text}"
        return

    # Przetworzenie danych z pierwszej strony
    all_products_data.extend(process_products(first_page_data.get("results", [])))
    
    total_pages = first_page_data.get("resultsNumberPage", 0)
    
    if total_pages <= 1:
        yield "Wszystkie dane zostały pobrane w jednym zapytaniu."
        yield from save_to_csv(all_products_data, OUTPUT_FILENAME)
        return

    yield f"Znaleziono {total_pages} stron. Rozpoczynam pobieranie współbieżne z użyciem 4 workerów..."

    # Pobieranie reszty stron współbieżnie
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Tworzenie listy zadań dla pozostałych stron
        futures = {executor.submit(fetch_page, page_num, full_url, headers): page_num for page_num in range(1, total_pages)}
        
        completed_count = 1  # Zaczynamy od 1, bo pierwsza strona już jest
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                result = future.result()
                if isinstance(result, list):
                    all_products_data.extend(result)
                else: # Jeśli fetch_page zwróciło błąd jako string
                    yield str(result)
            except Exception as exc:
                yield f"Błąd podczas przetwarzania strony {page_num + 1}: {exc}"
            
            completed_count += 1
            yield f"Ukończono {completed_count}/{total_pages} stron..."

    yield "Wszystkie strony pobrane. Trwa zapisywanie do pliku..."
    yield from save_to_csv(all_products_data, OUTPUT_FILENAME)

def save_to_csv(data, filename):
    if not data:
        yield "Nie znaleziono żadnych danych do zapisania."
        return

    headers = ["productId", "shopId", "menuId", "menuItemTextId"]
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)
        yield f"Ukończono! Dane zostały zapisane do pliku: {filename}"
    except IOError as e:
        yield f"Błąd zapisu do pliku CSV: {e}"

def run_downloader(base_url, api_key, progress_callback=None):
    """
    Główna funkcja uruchamiająca proces pobierania.
    Używa generatora do przekazywania komunikatów o postępie.
    """
    full_url = f"{base_url.rstrip('/')}/{ENDPOINT.lstrip('/')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    # Przekazujemy generator dalej. Worker w main.py zajmie się iterowaniem.
    yield from fetch_and_process_data(full_url, headers)