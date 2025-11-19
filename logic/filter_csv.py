import csv
import os

def run_filter(input_filename, output_filename, shop_id_to_keep, progress_callback=None):
    yield f"Rozpoczynam filtrowanie pliku {input_filename}..."
    yield f"Pozostaną tylko wiersze z shopId = {shop_id_to_keep}."

    try:
        with open(input_filename, 'r', newline='', encoding='utf-8') as infile, \
             open(output_filename, 'w', newline='', encoding='utf-8') as outfile:
            
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            
            try:
                header = next(reader)
                writer.writerow(header)
                shop_id_index = header.index('shopId')
            except (StopIteration, ValueError) as e:
                yield f"Błąd: Nie można odczytać nagłówka lub znaleźć kolumny 'shopId' w pliku {input_filename}. {e}"
                return

            processed_rows = 0
            for row in reader:
                if len(row) > shop_id_index and row[shop_id_index] == str(shop_id_to_keep):
                    writer.writerow(row)
                processed_rows += 1
                if processed_rows % 10000 == 0:
                    yield f"Przetworzono {processed_rows} wierszy..."
        
        yield f"Pomyślnie przefiltrowano plik. Wynik zapisano w {output_filename}."

    except FileNotFoundError:
        yield f"Błąd: Plik '{input_filename}' nie został znaleziony."
    except Exception as e:
        yield f"Wystąpił nieoczekiwany błąd podczas przetwarzania pliku: {e}"
        # Usuń tymczasowy plik w razie błędu
        if os.path.exists(output_filename):
            os.remove(output_filename)
