import pandas as pd
import requests
import concurrent.futures
from tqdm import tqdm
import os
import time
import csv
import re

def run_id_based_downloader(base_url, api_key, input_csv_path, progress_callback=None):
    """
    Pobiera dane produktów (nazwa, opisy) dla konkretnych ID z pliku CSV.
    """
    try:
        # Correctly construct the API URL from the base_url
        if not base_url.endswith('/'):
            base_url += '/'
        api_url = f"{base_url}api/admin/v7/products/products/search"

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-KEY": api_key
        }

        output_csv_file = input_csv_path.replace('.csv', '_products.csv')
        missing_ids_file = input_csv_path.replace('.csv', '_missing.txt')
        max_workers = 4

        def get_product_ids_from_csv(file_path):
            """Wczytuje identyfikatory produktów z pliku CSV."""
            try:
                df = pd.read_csv(file_path, on_bad_lines='skip')
                # Find column with IDs, trying common names
                id_col_name = None
                for col in ['@id', 'product_id', 'ID', 'Id', 'id']:
                    if col in df.columns:
                        id_col_name = col
                        break
                if id_col_name is None:
                    progress_callback("BŁĄD: W pliku CSV brakuje kolumny z ID produktu (np. '@id', 'product_id', 'ID').")
                    return set()
                
                return set(pd.to_numeric(df[id_col_name], errors='coerce').dropna().astype(int))
            except FileNotFoundError:
                progress_callback(f"BŁĄD: Plik {file_path} nie został znaleziony.")
                return set()

        def fetch_products_page(page_number):
            """Pobiera jedną stronę wyników z API z mechanizmem ponawiania prób."""
            payload = {"params": {"returnProducts": "active", "resultsPage": page_number}}
            max_retries = 5
            retry_delay = 15

            for attempt in range(max_retries):
                try:
                    response = requests.post(api_url, json=payload, headers=headers, timeout=30)
                    response.raise_for_status()
                    return response.json()
                except requests.exceptions.RequestException as e:
                    progress_callback(f"OSTRZEŻENIE: Błąd podczas pobierania strony {page_number} (próba {attempt + 1}/{max_retries}): {e}. Ponawiam za {retry_delay}s...")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        progress_callback(f"BŁĄD: Nie udało się pobrać danych dla strony {page_number} po {max_retries} próbach. Strona pominięta.")
                        return None
            return None

        yield f"Krok 1: Wczytywanie identyfikatorów produktów z pliku '{os.path.basename(input_csv_path)}'..."
        product_ids_to_find = get_product_ids_from_csv(input_csv_path)
        if not product_ids_to_find:
            yield "Nie znaleziono żadnych ID do przetworzenia. Zakończono."
            return
            
        yield f"Znaleziono {len(product_ids_to_find)} unikalnych ID produktów do wyszukania."

        yield "\nKrok 2: Ustalanie liczby stron do pobrania..."
        initial_data = fetch_products_page(0)
        if not initial_data or 'resultsNumberPage' not in initial_data:
            yield "BŁĄD: Nie udało się pobrać kluczowych informacji o liczbie stron. Sprawdź połączenie i klucz API."
            return
            
        total_pages = initial_data.get('resultsNumberPage', 0)
        total_products = initial_data.get('resultsNumberAll', 0)
        yield f"Znaleziono {total_products} wszystkich aktywnych produktów na {total_pages} stronach."

        yield f"\nKrok 3: Pobieranie wszystkich danych z API przy użyciu {max_workers} wątków..."
        
        all_products_data = []
        failed_pages = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_page = {executor.submit(fetch_products_page, page): page for page in range(total_pages)}
            
            processed_count = 0
            for future in concurrent.futures.as_completed(future_to_page):
                processed_count += 1
                page_num = future_to_page[future]
                page_data = future.result()
                if page_data and 'results' in page_data:
                    all_products_data.extend(page_data['results'])
                else:
                    failed_pages.append(page_num)
                
                if processed_count % 20 == 0 or processed_count == total_pages:
                     yield f"Pobrano {processed_count}/{total_pages} stron..."


        yield f"\nPobrano łącznie {len(all_products_data)} produktów."
        if failed_pages:
            yield f"OSTRZEŻENIE: Nie udało się pobrać danych dla następujących stron: {sorted(failed_pages)}"

        yield f"\nKrok 4: Przetwarzanie danych i zapisywanie wyników do '{os.path.basename(output_csv_file)}'..."
        
        header = ['ID', 'Nazwa', 'Opis krótki', 'Opis długi']
        try:
            with open(output_csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(header)
        except IOError as e:
            yield f"BŁĄD KRYTYCZNY: Nie można otworzyć pliku {output_csv_file} do zapisu: {e}"
            return

        found_product_ids = set()
        for product in all_products_data:
            product_id = product.get('productId')

            if product_id in product_ids_to_find:
                polish_description = next((desc for desc in product.get('productDescriptionsLangData', []) if desc.get('langId') == 'pol'), None)
                
                if polish_description:
                    row_data = [
                        product_id,
                        polish_description.get('productName', ''),
                        polish_description.get('productDescription', ''),
                        polish_description.get('productLongDescription', '')
                    ]
                    
                    try:
                        with open(output_csv_file, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(row_data)
                        found_product_ids.add(product_id)
                    except IOError as e:
                        yield f"BŁĄD: Nie udało się zapisać danych dla produktu ID {product_id}: {e}"

        yield f"\nPrzetworzono i zapisano dane dla {len(found_product_ids)} z {len(product_ids_to_find)} poszukiwanych produktów."
        
        yield f"\nKrok 5: Sprawdzanie brakujących identyfikatorów..."
        missing_ids = product_ids_to_find.difference(found_product_ids)
        
        if missing_ids:
            yield f"Znaleziono {len(missing_ids)} ID, których nie było w aktywnych produktach. Zapisywanie do '{os.path.basename(missing_ids_file)}'..."
            try:
                with open(missing_ids_file, 'w') as f:
                    for item_id in sorted(list(missing_ids)):
                        f.write(f"{item_id}\n")
            except IOError as e:
                yield f"BŁĄD: Nie udało się zapisać pliku z brakującymi ID: {e}"
        else:
            yield "Wszystkie identyfikatory z pliku wejściowego zostały odnalezione i przetworzone."

        yield f"\nZakończono pomyślnie! Wyniki w '{os.path.basename(output_csv_file)}'."

    except Exception as e:
        import traceback
        yield f"BŁĄD KRYTYCZNY w module pobierania po ID: {e}\n{traceback.format_exc()}"
