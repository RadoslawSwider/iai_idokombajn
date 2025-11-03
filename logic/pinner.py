import requests
import csv
import time

ENDPOINT = "api/admin/v7/products/products"
BATCH_SIZE = 100

def put_with_retry(url, json_payload, headers):
    """Wysyła zapytanie PUT z logiką ponawiania."""
    for attempt in range(10):
        try:
            response = requests.put(url, json=json_payload, headers=headers)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt < 9:
                time.sleep(60)
            else:
                raise e

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

def run_assignment_process(url, headers, tasks):
    if not tasks:
        yield "Brak zadań do wykonania dla podanych kryteriów."
        return
        
    yield f"Znaleziono {len(tasks)} produktów do przypisania. Dzielę na paczki po {BATCH_SIZE}..."
    
    batches = list(create_batches(tasks, BATCH_SIZE))
    total_batches = len(batches)
    
    for i, batch in enumerate(batches):
        yield f"Przetwarzanie paczki {i + 1} z {total_batches}..."
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
        
        try:
            response = put_with_retry(url, json_payload=full_payload, headers=headers)
            time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            error_message = f'Błąd serwera po 10 próbach: {e}'
            try:
                error_details = response.text
                error_message += f' | Odpowiedź: {error_details}'
            except Exception:
                pass
            yield f"Błąd podczas przetwarzania paczki nr {i+1}: {error_message}"
            continue
            
    yield "Zakończono! Wszystkie paczki zostały przetworzone."

def run_pinner(base_url, api_key, shop_id, menu_id, csv_filename):
    full_url = f"{base_url.rstrip('/')}/{ENDPOINT.lstrip('/')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    
    tasks_generator = read_and_filter_csv(csv_filename, shop_id, menu_id)
    
    # First yield is a status message or an error
    first_yield = next(tasks_generator, None)
    if isinstance(first_yield, str) and first_yield.startswith("Błąd"):
        yield first_yield
        return
    yield first_yield # Pass the status message

    tasks = next(tasks_generator, None)
    if tasks is None: # Error or no tasks found
        return

    yield from run_assignment_process(full_url, headers, tasks)
