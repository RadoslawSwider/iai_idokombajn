import requests
import csv
import time

ENDPOINT = "api/admin/v7/products/products"
BATCH_SIZE = 100
CSV_INPUT_FILE = "produkty_menu_final.csv"

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
    try:
        with open(filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if int(row['shopId']) == target_shop_id and int(row['menuId']) == target_menu_id:
                    tasks.append(row)
    except FileNotFoundError:
        yield f"Błąd krytyczny: Nie znaleziono pliku wejściowego '{filename}'."
        yield "Upewnij się, że plik został najpierw pobrany."
        return
    except (ValueError, KeyError) as e:
        yield f"Błąd w strukturze pliku CSV: {e}."
        return
    
    yield tasks

def create_batches(data, batch_size):
    for i in range(0, len(data), batch_size):
        yield data[i:i + batch_size]

def run_update_process(url, headers, tasks):
    if not tasks:
        yield "Brak zadań do wykonania. Nie znaleziono pasujących produktów w pliku CSV."
        return
        
    yield f"Znaleziono {len(tasks)} powiązań menu do usunięcia. Dzielę na paczki po {BATCH_SIZE}..."
    
    batches = list(create_batches(tasks, BATCH_SIZE))
    total_batches = len(batches)
    
    for i, batch in enumerate(batches):
        yield f"Przetwarzanie paczki {i + 1} z {total_batches}..."
        products_payload = []
        for item in batch:
            product_update_instruction = {
                "productId": int(item['productId']),
                "productMenuItems": [
                    {
                        "productMenuOperation": "delete_product",
                        "shopId": int(item['shopId']),
                        "menuId": int(item['menuId']),
                        "menuItemTextId": item['menuItemTextId']
                    }
                ]
            }
            products_payload.append(product_update_instruction)
        
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
            
    yield "Zakończono przetwarzanie wszystkich paczek."

def run_unpinner(base_url, api_key, shop_id, menu_id, progress_callback=None):
    full_url = f"{base_url.rstrip('/')}/{ENDPOINT.lstrip('/')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-KEY": api_key
    }
    
    tasks_generator = read_and_filter_csv(CSV_INPUT_FILE, shop_id, menu_id)
    tasks = next(tasks_generator, None)

    if tasks is None: # Error occurred in read_and_filter_csv
        yield from tasks_generator
        return

    yield from run_update_process(full_url, headers, tasks)
