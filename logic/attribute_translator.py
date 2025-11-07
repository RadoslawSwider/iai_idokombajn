
import pandas as pd
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import logging

# Konfiguracja
MAX_RETRIES = 5
RETRY_DELAY = 30  # sekundy
RATE_LIMIT = 1  # 1 zapytanie na sekundę

class RateLimiter:
    def __init__(self, rate_limit):
        self.rate_limit = rate_limit
        self.last_call = 0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            elapsed = time.monotonic() - self.last_call
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
            self.last_call = time.monotonic()

def translate_text(text, target_language, rate_limiter):
    if not text or not text.strip():
        return text, None

    for attempt in range(MAX_RETRIES):
        try:
            rate_limiter.wait()
            translated_text = GoogleTranslator(source='pl', target=target_language).translate(text)
            return translated_text, None
        except Exception as e:
            logging.warning(f"Błąd tłumaczenia (próba {attempt + 1}/{MAX_RETRIES}): {e}. Ponawiam za {RETRY_DELAY}s.")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    return text, "Nie udało się przetłumaczyć tekstu po wielu próbach."

def process_row(row, id_column, description_column, target_language, rate_limiter):
    product_id = row[id_column]
    description = row[description_column]
    errors = []

    if not isinstance(description, str) or not description.strip():
        return description, []

    soup = BeautifulSoup(description, 'html.parser')
    
    for tag in soup.find_all(True, alt=True):
        original_alt = tag['alt']
        translated_alt, error = translate_text(original_alt, target_language, rate_limiter)
        if error:
            errors.append(f"ID: {product_id}, Atrybut: alt, Błąd: {error}, Oryginał: '{original_alt}'")
        tag['alt'] = translated_alt

    for tag in soup.find_all(True, title=True):
        original_title = tag['title']
        translated_title, error = translate_text(original_title, target_language, rate_limiter)
        if error:
            errors.append(f"ID: {product_id}, Atrybut: title, Błąd: {error}, Oryginał: '{original_title}'")
        tag['title'] = translated_title

    return str(soup), errors

def run_attribute_translator(input_path, id_column, description_column, target_language, num_workers, batch_size, progress_callback):
    try:
        progress_callback("Etap 1/4: Wczytywanie pliku i zbieranie tekstów...")
        df = pd.read_csv(input_path, on_bad_lines='skip').fillna('')
        
        if id_column not in df.columns or description_column not in df.columns:
            raise ValueError("Wybrane kolumny nie istnieją w pliku.")

        texts_to_translate = set()
        for desc in df[description_column]:
            if isinstance(desc, str) and desc.strip():
                soup = BeautifulSoup(desc, 'html.parser')
                for tag in soup.find_all(True, alt=True):
                    if tag['alt'].strip(): texts_to_translate.add(tag['alt'])
                for tag in soup.find_all(True, title=True):
                    if tag['title'].strip(): texts_to_translate.add(tag['title'])

        if not texts_to_translate:
            progress_callback("Nie znaleziono żadnych atrybutów 'alt' lub 'title' do tłumaczenia.")
            return "Zakończono. Nie znaleziono tekstów."

        progress_callback(f"Etap 2/4: Tłumaczenie {len(texts_to_translate)} unikalnych tekstów...")
        
        source_texts = list(texts_to_translate)
        translated_texts = {}
        errors = []
        rate_limiter = RateLimiter(RATE_LIMIT)
        translator = GoogleTranslator(source='pl', target=target_language)

        # Dzielenie na paczki (batch)
        for i in range(0, len(source_texts), batch_size):
            batch = source_texts[i:i+batch_size]
            progress_callback(f"Przygotowuję paczkę {i//batch_size + 1}/{(len(source_texts) + batch_size - 1)//batch_size}...")
            for attempt in range(MAX_RETRIES):
                try:
                    rate_limiter.wait()
                    progress_callback(f"Wysyłam paczkę do tłumaczenia...")
                    translated_batch = translator.translate_batch(batch)
                    progress_callback(f"Otrzymano odpowiedź dla paczki.")
                    for original, translated in zip(batch, translated_batch):
                        if translated:
                            translated_texts[original] = translated
                        else:
                            translated_texts[original] = original # Zostaw oryginał w razie błędu
                            errors.append(f"Błąd tłumaczenia dla tekstu: '{original}' (otrzymano pustą odpowiedź)")
                    progress_callback(f"Przetłumaczono {min(i + len(batch), len(source_texts))}/{len(source_texts)} tekstów...")
                    break # Sukces, wyjdź z pętli ponowień
                except Exception as e:
                    logging.warning(f"Błąd tłumaczenia paczki (próba {attempt + 1}/{MAX_RETRIES}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
                    else:
                        errors.append(f"Nie udało się przetłumaczyć paczki po {MAX_RETRIES} próbach. Błąd: {e}")
                        # Zapisz oryginalne teksty z paczki, aby ich nie stracić
                        for text in batch:
                            if text not in translated_texts:
                                translated_texts[text] = text
                        break # Idź do następnej paczki

        progress_callback("Etap 3/4: Aktualizowanie opisów w pliku...")
        
        output_column_name = f"{description_column}_generated"
        df[output_column_name] = df[description_column]

        def update_description(desc):
            if not isinstance(desc, str) or not desc.strip():
                return desc
            soup = BeautifulSoup(desc, 'html.parser')
            modified = False
            for tag in soup.find_all(True, alt=True):
                if tag['alt'] in translated_texts:
                    tag['alt'] = translated_texts[tag['alt']]
                    modified = True
            for tag in soup.find_all(True, title=True):
                if tag['title'] in translated_texts:
                    tag['title'] = translated_texts[tag['title']]
                    modified = True
            return str(soup) if modified else desc

        # Użycie apply jest szybsze dla operacji na kolumnach
        df[output_column_name] = df[output_column_name].apply(update_description)

        if errors:
            error_column_name = "błędy"
            df[error_column_name] = pd.Series(dtype='object')
            df.at[0, error_column_name] = "\n".join(errors)

        progress_callback("Etap 4/4: Zapisywanie wyników...")
        output_path = input_path.replace(".csv", "_generated.csv")
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        progress_callback(f"Zakończono! Plik zapisano w: {output_path}")
        if errors:
            progress_callback(f"Wystąpiły błędy podczas tłumaczenia. Sprawdź kolumnę 'błędy'.")
            
        return f"Proces zakończony. Wyniki w {output_path}"

    except Exception as e:
        logging.error(f"Krytyczny błąd w `run_attribute_translator`: {e}")
        progress_callback(f"Błąd krytyczny: {e}")
        return f"Błąd: {e}"
