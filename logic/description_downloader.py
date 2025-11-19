import requests
import csv
import time

ENDPOINT = "/api/admin/v7/products/products/search"
OUTPUT_FILENAME = "produkty.csv"

def post_with_retry(full_url, json_payload, headers):
    """Wysyła zapytanie POST z logiką ponawiania."""
    for attempt in range(10):
        try:
            response = requests.post(full_url, json=json_payload, headers=headers, timeout=60)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt < 9:
                time.sleep(60)
            else:
                raise e

def fetch_all_products(base_url, api_key):
    """Pobiera wszystkie produkty z API, używając paginacji."""
    full_url = f"{base_url.rstrip('/')}{ENDPOINT}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    
    all_products = []
    current_page = 0
    total_pages = 1

    yield "Rozpoczynam pobieranie danych o produktach..."

    while current_page < total_pages:
        payload = {
            "params": {
                "returnProducts": "active",
                "resultsPage": current_page,
                "resultsLimit": 100
            }
        }
        
        if total_pages > 1:
            yield f'Pobieranie strony {current_page + 1}/{total_pages}...'

        try:
            response = post_with_retry(full_url, json_payload=payload, headers=headers)
            data = response.json()

            if current_page == 0:
                total_pages = data.get('resultsNumberPage', 1)
                total_products = data.get('resultsNumberAll', 0)
                
                if total_pages == 0:
                    yield "API zwróciło 0 stron. Sprawdź, czy w sklepie są aktywne produkty."
                    return
                
                yield f"Znaleziono {total_products} produktów na {total_pages} stronach. Rozpoczynam pobieranie..."
                if total_pages > 1:
                    time.sleep(1)

            products_on_page = data.get('results', [])
            if not products_on_page and current_page > 0:
                yield f"Ostrzeżenie: Strona {current_page + 1} nie zawierała produktów. Kończę pobieranie."
                break
                
            all_products.extend(products_on_page)
            current_page += 1

        except requests.exceptions.RequestException as e:
            yield f"Krytyczny błąd po 10 próbach: {e}"
            return
        except ValueError:
            yield f"BŁĄD: Nie udało się zdekodować odpowiedzi JSON."
            return
    
    yield "\nPobieranie zakończone."
    yield from process_and_save_to_csv(all_products)

def process_and_save_to_csv(products):
    """Przetwarza listę produktów i zapisuje je do pliku CSV."""
    if not products:
        yield "Brak produktów do przetworzenia."
        return

    yield f"Przetwarzam {len(products)} produktów i przygotowuję plik CSV..."
    headers = ['productId']
    
    # Dynamiczne tworzenie nagłówków na podstawie języków w pierwszym produkcie
    if products:
        first_product_langs = products[0].get('productDescriptionsLangData', [])
        languages = sorted([lang_data['langId'] for lang_data in first_product_langs])
        
        for lang in languages:
            headers.append(f'productName_{lang}')
            headers.append(f'productDescription_{lang}')
            headers.append(f'productLongDescription_{lang}')
            
    rows_to_write = []
    for product in products:
        row_data = {'productId': product.get('productId')}
        
        descriptions_by_lang = {desc['langId']: desc for desc in product.get('productDescriptionsLangData', [])}
        
        for lang in languages:
            lang_data = descriptions_by_lang.get(lang, {})
            row_data[f'productName_{lang}'] = lang_data.get('productName', '')
            row_data[f'productDescription_{lang}'] = lang_data.get('productDescription', '')
            row_data[f'productLongDescription_{lang}'] = lang_data.get('productLongDescription', '')
            
        rows_to_write.append(row_data)

    try:
        with open(OUTPUT_FILENAME, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows_to_write)
        yield f"Sukces! Dane {len(products)} produktów zostały zapisane do pliku '{OUTPUT_FILENAME}'."
    except IOError as io_err:
        yield f"BŁĄD: Nie udało się zapisać pliku '{OUTPUT_FILENAME}'. Powód: {io_err}"

def run_description_downloader(base_url, api_key, progress_callback=None):
    """Główna funkcja uruchamiająca pobieranie opisów."""
    yield from fetch_all_products(base_url, api_key)
