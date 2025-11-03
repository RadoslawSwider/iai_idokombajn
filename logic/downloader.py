import requests
import csv
import time
from tqdm import tqdm

ENDPOINT = "api/admin/v7/products/products/search"
OUTPUT_FILENAME = "produkty_menu_final.csv"

def post_with_retry(full_url, json_payload, headers):
    """Wysyła zapytanie POST z logiką ponawiania."""
    for attempt in range(10):
        try:
            response = requests.post(full_url, json=json_payload, headers=headers)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt < 9:
                time.sleep(60)
            else:
                raise e

def process_products(products, all_products_data):
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
                for lang_data in menu_descriptions:
                    if lang_data.get("langId") == "pol":
                        target_description = lang_data
                        break
                if not target_description:
                    target_description = menu_descriptions[0]
                extracted_row = {
                    "productId": product_id,
                    "shopId": shop_id,
                    "menuId": menu_id,
                    "menuItemTextId": target_description.get("menuItemTextId")
                }
                all_products_data.append(extracted_row)

def fetch_and_process_data(full_url, headers):
    all_products_data = []
    yield "Pobieranie pierwszej strony, aby ustalić liczbę wszystkich stron..."
    payload_page_0 = {"params": {"returnProducts": "active", "resultsPage": 0}}
    
    try:
        response = post_with_retry(full_url, json_payload=payload_page_0, headers=headers)
        first_page_data = response.json()
    except requests.exceptions.RequestException as e:
        yield f"Krytyczny błąd: Nie udało się pobrać pierwszej strony danych po 10 próbach. {e}"
        yield "Sprawdź, czy podałeś poprawny Base URL i czy serwer jest dostępny."
        return
    except ValueError:
        yield "Krytyczny błąd: Nie udało się zdekodować odpowiedzi JSON. Sprawdź poprawność klucza API."
        yield f"Odpowiedź serwera: {response.text}"
        return

    process_products(first_page_data.get("results", []), all_products_data)
    total_pages = first_page_data.get("resultsNumberPage", 0)
    
    if total_pages <= 1:
        yield "Wszystkie dane zostały pobrane w jednym zapytaniu."
        yield from save_to_csv(all_products_data, OUTPUT_FILENAME)
        return

    yield f"Znaleziono {total_pages} stron. Pobieram pozostałe dane..."

    for page_num in range(1, total_pages):
        yield f"Pobieranie strony {page_num + 1} z {total_pages}..."
        payload = {"params": {"returnProducts": "active", "resultsPage": page_num}}
        try:
            response = post_with_retry(full_url, json_payload=payload, headers=headers)
            data = response.json()
            process_products(data.get("results", []), all_products_data)
        except requests.exceptions.RequestException as e:
            yield f"Błąd podczas pobierania strony {page_num}: {e}. Pomijam."
            continue
        except ValueError:
            yield f"Błąd dekodowania JSON na stronie {page_num}. Pomijam tę stronę."
            continue
    
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

def run_downloader(base_url, api_key):
    full_url = f"{base_url.rstrip('/')}/{ENDPOINT.lstrip('/')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    yield from fetch_and_process_data(full_url, headers)
