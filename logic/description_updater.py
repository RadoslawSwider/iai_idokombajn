
import pandas as pd
import requests
import time
import math
from PyQt6.QtCore import QObject, pyqtSignal

class DescriptionUpdaterWorker(QObject):
    progress = pyqtSignal(int, int, str) # current, total, message
    finished = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, file_path, api_key, base_url, shop_id, lang_id, batch_size, column_map):
        super().__init__()
        self.file_path = file_path
        self.api_key = api_key
        self.base_url = base_url
        self.shop_id = shop_id
        self.lang_id = lang_id
        self.batch_size = batch_size
        self.column_map = column_map
        self.is_cancelled = False
        self.has_errors = False

    def run(self):
        try:
            self.log_message.emit("Rozpoczynanie procesu aktualizacji...")
            df = pd.read_csv(self.file_path).fillna('')
            self.log_message.emit(f"Wczytano {len(df)} wierszy z pliku CSV.")

            # Validate required columns
            for key, col_name in self.column_map.items():
                if col_name and col_name not in df.columns:
                    raise ValueError(f"Brak wymaganej, zmapowanej kolumny w pliku CSV: '{col_name}'")

            total_rows = len(df)
            num_batches = math.ceil(total_rows / self.batch_size)
            
            endpoint = "api/admin/v7/products/descriptions"
            url = f"{self.base_url.rstrip('/')}/{endpoint}"
            
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "X-API-KEY": self.api_key
            }

            for i in range(num_batches):
                if self.is_cancelled:
                    self.log_message.emit("Proces anulowany przez użytkownika.")
                    break

                start_index = i * self.batch_size
                end_index = start_index + self.batch_size
                batch_df = df.iloc[start_index:end_index]
                
                products_payload = []
                for _, row in batch_df.iterrows():
                    # Base structure for language data
                    lang_data = {
                        "langId": self.lang_id,
                        "shopId": self.shop_id,
                    }

                    # Dynamically add mapped fields
                    if self.column_map.get("productName"):
                        lang_data["productName"] = str(row[self.column_map["productName"]])
                    
                    if self.column_map.get("productLongDescription"):
                        lang_data["productLongDescription"] = str(row[self.column_map["productLongDescription"]])

                    if self.column_map.get("productDescription"):
                        lang_data["productDescription"] = str(row[self.column_map["productDescription"]])

                    # Final product data structure
                    product_data = {
                        "productIdent": {
                            "productIdentType": "id",
                            "identValue": str(row[self.column_map['identValue']])
                        },
                        "productDescriptionsLangData": [lang_data]
                    }
                    products_payload.append(product_data)

                payload = {"params": {"products": products_payload}}
                
                self.log_message.emit(f"Wysyłanie paczki {i+1}/{num_batches} ({len(batch_df)} produktów)...")
                
                try:
                    response = requests.put(url, json=payload, headers=headers, timeout=30)
                    
                    if 200 <= response.status_code < 300:
                        self.log_message.emit(f"✅ Paczka {i+1} przetworzona pomyślnie (Status: {response.status_code}).")
                    else:
                        self.log_message.emit(f"❌ Błąd przetwarzania paczki {i+1} (Status: {response.status_code}). Odpowiedź serwera:")
                        self.log_message.emit(response.text)
                        self.has_errors = True
                
                except requests.exceptions.RequestException as e:
                    self.log_message.emit(f"❌ Błąd sieci podczas wysyłania paczki {i+1}: {e}")
                    self.has_errors = True

                self.progress.emit(end_index if end_index < total_rows else total_rows, total_rows, f"Przetworzono {i+1}/{num_batches} paczek")
                time.sleep(0.5) # Small delay to avoid overwhelming the API

            if not self.is_cancelled:
                self.log_message.emit("Zakończono proces aktualizacji.")
                if self.has_errors:
                    self.finished.emit("Zakończono z błędami.")
                else:
                    self.finished.emit("Zakończono pomyślnie.")
            else:
                self.finished.emit("Anulowano.")

        except Exception as e:
            self.log_message.emit(f"BŁĄD KRYTYCZNY: {e}")
            self.finished.emit(f"Błąd: {e}")

    def cancel(self):
        self.is_cancelled = True
        self.has_errors = False
