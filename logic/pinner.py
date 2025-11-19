import requests
import csv
import time
import os
import threading
from typing import Generator, List, Dict, Any

ENDPOINT = "api/admin/v7/products/products"
BATCH_SIZE = 30
ERROR_FILE = "pinner_errors.csv"
REQUEST_INTERVAL = 1.0  # Czas w sekundach pomiędzy zapytaniami (1.0 = 1 zapytanie/sek)

# --- NOWA LOGIKA PRZYPINANIA PO ID ---

def process_batch_by_id(
    batch: List[int],
    url: str,
    headers: Dict[str, str],
    batch_number: int,
    total_batches: int,
    rate_limit_lock: threading.Lock,
    last_request_time: Dict[str, float],
    timeout: int,
    delay: int,
    target_shop_id: int,
    target_menu_id: int,
    target_node_id: int
) -> Generator[str, None, None]:
    """Przetwarza paczkę produktów, przypinając je do docelowego węzła menu po jego ID."""
    if not batch:
        yield f"Paczka {batch_number} z {total_batches} jest pusta, pomijam."
        return

    products_payload = []
    for product_id in batch:
        product_assignment_instruction = {
            "productId": product_id,
            "productMenuItems": [
                {
                    "productMenuOperation": "add_product",
                    "menuItemId": target_node_id,  # Kluczowa zmiana: używamy ID węzła
                    "shopId": target_shop_id,
                    "menuId": target_menu_id
                }
            ]
        }
        products_payload.append(product_assignment_instruction)
    
    full_payload = {"params": {"products": products_payload}}

    with rate_limit_lock:
        elapsed = time.monotonic() - last_request_time["value"]
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        last_request_time["value"] = time.monotonic()

    messages_to_yield = []
    yield f"Przetwarzam paczkę {batch_number}/{total_batches} (przypinanie po ID)..."
    
    result, attempts = put_with_retry(url, json_payload=full_payload, headers=headers, timeout=timeout, log_callback=lambda msg: messages_to_yield.append(msg))
    
    for msg in messages_to_yield:
        yield msg

    if isinstance(result, requests.exceptions.RequestException):
        error = result
        try:
            file_exists = os.path.isfile(ERROR_FILE)
            with open(ERROR_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['productId', 'error'])
                for product_id in batch:
                    writer.writerow([product_id, str(error)])
            yield f"BŁĄD podczas przetwarzania paczki nr {batch_number}. Zapisano ID produktów do {ERROR_FILE}."
        except Exception as log_e:
            yield f"KRYTYCZNY BŁĄD podczas przetwarzania paczki nr {batch_number}. NIE UDAŁO SIĘ zapisać do pliku błędów: {log_e}"
    elif isinstance(result, requests.Response):
        response_summary = f"Status: {result.status_code}, Odpowiedź: {result.text[:150]}..." if result.text else f"Status: {result.status_code}"
        if attempts > 1:
            yield f"SUKCES: Paczka {batch_number}/{total_batches} została pomyślnie przetworzona (po {attempts} próbach). {response_summary}"
        else:
            yield f"Paczka {batch_number}/{total_batches} została pomyślnie przetworzona. {response_summary}"
        
        if delay > 0:
            yield f"Odczekuję {delay} sekund..."
            time.sleep(delay)

def run_pinner_by_id(
    base_url: str,
    api_key: str,
    product_ids: List[int],
    target_shop_id: int,
    target_menu_id: int,
    target_node_id: int,
    timeout: int = 120,
    delay: int = 0,
    long_pause_batch_count: int = 100,
    long_pause_duration_minutes: int = 5,
    progress_callback=None
) -> Generator[str, None, None]:
    """Orkiestruje proces przypinania listy produktów do konkretnego węzła menu po jego ID."""
    if os.path.exists(ERROR_FILE):
        try:
            os.remove(ERROR_FILE)
            yield f"Usunięto stary plik błędów: {ERROR_FILE}"
        except OSError as e:
            yield f"Ostrzeżenie: Nie można usunąć starego pliku błędów {ERROR_FILE}: {e}"

    full_url = f"{base_url.rstrip('/')}/{ENDPOINT.lstrip('/')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }

    if not product_ids:
        yield "Brak produktów do przypisania."
        return
        
    yield f"Znaleziono {len(product_ids)} produktów do przypisania do węzła ID: {target_node_id}. Dzielę na paczki po {BATCH_SIZE}..."
    
    batches = list(create_batches(product_ids, BATCH_SIZE))
    total_batches = len(batches)
    
    rate_limit_lock = threading.Lock()
    last_request_time = {"value": 0}

    yield "Uruchamiam przetwarzanie sekwencyjne (paczka po paczce)..."
    
    for i, batch in enumerate(batches):
        batch_number = i + 1
        yield from process_batch_by_id(
            batch, full_url, headers, batch_number, total_batches, 
            rate_limit_lock, last_request_time, timeout, delay,
            target_shop_id, target_menu_id, target_node_id
        )
        
        if long_pause_batch_count > 0 and batch_number % long_pause_batch_count == 0 and batch_number < total_batches:
            yield f"Przetworzono {long_pause_batch_count} paczek. Uruchamiam długą pauzę na {long_pause_duration_minutes} minut."
            time.sleep(long_pause_duration_minutes * 60)
            yield "Pauza zakończona. Wznawiam przetwarzanie."
            
    yield f"Zakończono! Wszystkie paczki zostały przetworzone. Sprawdź plik {ERROR_FILE}, jeśli wystąpiły błędy."


# --- STARA LOGIKA (POZOSTAWIONA DLA ZACHOWANIA KOMPATYBILNOŚCI) ---

def put_with_retry(url, json_payload, headers, timeout, log_callback):
    """
    Wysyła zapytanie PUT z logiką ponawiania.
    Zwraca krotkę (wynik, liczba_prób), gdzie wynik to obiekt odpowiedzi lub wyjątek.
    """
    start_time = time.monotonic()
    max_retry_duration = 60 * 60  # 1 godzina
    wait_time = 5 * 60  # 5 minut
    attempt = 0

    while True:
        attempt += 1
        try:
            response = requests.put(url, json=json_payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response, attempt
        except requests.exceptions.RequestException as e:
            last_exception = e
            elapsed_time = time.monotonic() - start_time
            
            if elapsed_time + wait_time > max_retry_duration:
                log_callback(f"Błąd krytyczny po {attempt} próbach. Czas ponawiania przekroczył 1 godzinę. Ostatni błąd: {e}")
                return last_exception, attempt

            log_callback(f"Błąd zapytania (próba {attempt}): {e}. Ponawiam próbę za {int(wait_time / 60)} minut...")
            time.sleep(wait_time)


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

def process_batch(batch, url, headers, batch_number, total_batches, rate_limit_lock, last_request_time, timeout, delay):
    if not batch:
        yield f"Paczka {batch_number} z {total_batches} jest pusta, pomijam."
        return

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

    with rate_limit_lock:
        elapsed = time.monotonic() - last_request_time["value"]
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        last_request_time["value"] = time.monotonic()

    messages_to_yield = []
    yield f"Przetwarzam paczkę {batch_number} z {total_batches}..."
    
    result, attempts = put_with_retry(url, json_payload=full_payload, headers=headers, timeout=timeout, log_callback=lambda msg: messages_to_yield.append(msg))
    
    for msg in messages_to_yield:
        yield msg

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
            yield f"BŁĄD podczas przetwarzania paczki nr {batch_number}. Zapisano do {ERROR_FILE}."
        except Exception as log_e:
            yield f"KRYTYCZNY BŁĄD podczas przetwarzania paczki nr {batch_number}. NIE UDAŁO SIĘ zapisać do pliku błędów: {log_e}"
    elif isinstance(result, requests.Response):
        response_summary = f"Status: {result.status_code}, Odpowiedź: {result.text[:150]}..." if result.text else f"Status: {result.status_code}"
        if attempts > 1:
            yield f"SUKCES: Paczka {batch_number} z {total_batches} została pomyślnie przetworzona (po {attempts} próbach). {response_summary}"
        else:
            yield f"Paczka {batch_number} z {total_batches} została pomyślnie przetworzona. {response_summary}"
        
        if delay > 0:
            yield f"Odczekuję {delay} sekund..."
            time.sleep(delay)


def run_assignment_process(url, headers, tasks, timeout, delay, long_pause_batch_count, long_pause_duration_minutes):
    if not tasks:
        yield "Brak zadań do wykonania dla podanych kryteriów."
        return
        
    yield f"Znaleziono {len(tasks)} produktów do przypisania. Dzielę na paczki po {BATCH_SIZE}..."
    
    batches = list(create_batches(tasks, BATCH_SIZE))
    total_batches = len(batches)
    
    rate_limit_lock = threading.Lock()
    last_request_time = {"value": 0}

    yield "Uruchamiam przetwarzanie sekwencyjne (paczka po paczce)..."
    
    for i, batch in enumerate(batches):
        batch_number = i + 1
        yield from process_batch(batch, url, headers, batch_number, total_batches, rate_limit_lock, last_request_time, timeout, delay)
        
        if long_pause_batch_count > 0 and batch_number % long_pause_batch_count == 0 and batch_number < total_batches:
            yield f"Przetworzono {long_pause_batch_count} paczek. Uruchamiam długą pauzę na {long_pause_duration_minutes} minut."
            time.sleep(long_pause_duration_minutes * 60)
            yield "Pauza zakończona. Wznawiam przetwarzanie."
            
    yield f"Zakończono! Wszystkie paczki zostały przetworzone. Sprawdź plik {ERROR_FILE}, jeśli wystąpiły błędy."

def run_pinner(base_url, api_key, shop_id, menu_id, csv_filename, timeout=120, delay=0, long_pause_batch_count=100, long_pause_duration_minutes=5, progress_callback=None):
    if os.path.basename(csv_filename) != ERROR_FILE and os.path.exists(ERROR_FILE):
        try:
            os.remove(ERROR_FILE)
            yield f"Usunięto stary plik błędów: {ERROR_FILE}"
        except OSError as e:
            yield f"Ostrzeżenie: Nie można usunąć starego pliku błędów {ERROR_FILE}: {e}"

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
    if not tasks:
        yield "Nie znaleziono żadnych pasujących produktów w pliku CSV."
        return

    yield from run_assignment_process(full_url, headers, tasks, timeout, delay, long_pause_batch_count, long_pause_duration_minutes)