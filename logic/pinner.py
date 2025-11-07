import requests
import csv
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ENDPOINT = "api/admin/v7/products/products"
BATCH_SIZE = 50
ERROR_FILE = "pinner_errors.csv"
REQUEST_INTERVAL = 1.0  # Czas w sekundach pomiędzy zapytaniami (1.0 = 1 zapytanie/sek)

def put_with_retry(url, json_payload, headers):
    """Wysyła zapytanie PUT z logiką ponawiania (3 próby co 30 sekund)."""
    last_exception = None
    for attempt in range(3):
        try:
            response = requests.put(url, json=json_payload, headers=headers, timeout=30)
            response.raise_for_status()
            return response  # Sukces
        except requests.exceptions.RequestException as e:
            last_exception = e
            time.sleep(30)
    return last_exception  # Zwraca wyjątek po nieudanych próbach

def read_and_filter_csv(filename, target_shop_id, target_menu_id):
    tasks = []
    expected_columns = ['productId', 'shopId', 'menuId', 'menuItemTextId']

    try:
        with open(filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            if not all(col in reader.fieldnames for col in expected_columns):
                yield f"Błąd: Plik CSV nie zawiera wszystkich wymaganych kolumn. Oczekiwane: {expected_columns}"
                return

            yield "Wczytywanie i filtrowanie pliku CSV..."
            for row in reader:
                try:
                    shop_id = int(row['shopId'].strip())
                    menu_id = int(row['menuId'].strip())
                    if shop_id == target_shop_id and menu_id == target_menu_id:
                        tasks.append(row)
                except (ValueError, AttributeError):
                    continue
    except FileNotFoundError:
        yield f"Błąd krytyczny: Nie znaleziono pliku wejściowego '{filename}'."
        return
    
    yield tasks

def create_batches(data, batch_size):
    for i in range(0, len(data), batch_size):
        yield data[i:i + batch_size]

def process_batch(batch, url, headers, batch_number, total_batches, rate_limit_lock, last_request_time):
    """Przetwarza pojedynczą paczkę danych, uwzględniając limit zapytań i logując błędy."""
    if not batch:
        return f"Paczka {batch_number} z {total_batches} jest pusta, pomijam."

    products_payload = []
    for item in batch:
        product_assignment_instruction = {
            "productId": int(item['productId'].strip()),
            "productMenuItems": [
                {
                    "productMenuOperation": "add_product",
                    "menuItemTextId": item['menuItemTextId'],
                    "shopId": int(item['shopId'].strip()),
                    "menuId": int(item['menuId'].strip())
                }
            ]
        }
        products_payload.append(product_assignment_instruction)
    
    full_payload = {"params": {"products": products_payload}}

    # Logika "inteligentnego hamulca" (Rate Limiter)
    with rate_limit_lock:
        elapsed = time.monotonic() - last_request_time["value"]
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        last_request_time["value"] = time.monotonic()

    result = put_with_retry(url, json_payload=full_payload, headers=headers)
    
    if isinstance(result, requests.exceptions.RequestException):
        error = result
        try:
            file_exists = os.path.isfile(ERROR_FILE)
            with open(ERROR_FILE, 'a', newline='', encoding='utf-8') as f:
                fieldnames = list(batch[0].keys()) + ['error']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                for item in batch:
                    item_with_error = item.copy()
                    item_with_error['error'] = str(error)
                    writer.writerow(item_with_error)
            return f"Błąd podczas przetwarzania paczki nr {batch_number}. Zapisano do {ERROR_FILE}."
        except Exception as log_e:
            return f"Błąd podczas przetwarzania paczki nr {batch_number}. NIE UDAŁO SIĘ zapisać do pliku błędów: {log_e}"
    else:
        return f"Paczka {batch_number} z {total_batches} została pomyślnie przetworzona."

def run_assignment_process(url, headers, tasks, num_workers):
    if not tasks:
        yield "Brak zadań do wykonania dla podanych kryteriów."
        return
        
    yield f"Znaleziono {len(tasks)} produktów do przypisania. Dzielę na paczki po {BATCH_SIZE}..."
    
    batches = list(create_batches(tasks, BATCH_SIZE))
    total_batches = len(batches)
    
    # Stan dla "inteligentnego hamulca"
    rate_limit_lock = threading.Lock()
    last_request_time = {"value": 0}

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        yield f"Uruchamiam {num_workers} workerów z limitem ~1 zapytania/sekundę..."
        futures = [executor.submit(process_batch, batch, url, headers, i + 1, total_batches, rate_limit_lock, last_request_time) for i, batch in enumerate(batches)]
        
        for future in as_completed(futures):
            yield future.result()
            
    yield f"Zakończono! Wszystkie paczki zostały przetworzone. Sprawdź plik {ERROR_FILE}, jeśli wystąpiły błędy."

def run_pinner(base_url, api_key, shop_id, menu_id, csv_filename, num_workers=4):
    if os.path.exists(ERROR_FILE):
        os.remove(ERROR_FILE)

    full_url = f"{base_url.rstrip('/')}/{ENDPOINT.lstrip('/')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    
    tasks_generator = read_and_filter_csv(csv_filename, shop_id, menu_id)
    
    first_yield = next(tasks_generator, None)
    if isinstance(first_yield, str) and first_yield.startswith("Błąd"):
        yield first_yield
        return
    yield first_yield

    tasks = next(tasks_generator, None)
    if tasks is None:
        return

    yield from run_assignment_process(full_url, headers, tasks, num_workers)
