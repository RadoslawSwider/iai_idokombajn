
import pandas as pd
import time
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLineEdit, 
    QTextEdit, QProgressBar, QLabel, QFileDialog, QCheckBox,
    QMessageBox, QDialogButtonBox, QGroupBox, QGridLayout, QSpinBox
)
from PyQt6.QtCore import QThread, pyqtSignal, QObject, QSettings
from deep_translator import GoogleTranslator

from logic.description_updater import DescriptionUpdaterWorker

class DescriptionUpdaterDialog(QDialog):
    def __init__(self, api_key, base_url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aktualizator Nazw i Opisów Produktów")
        self.setGeometry(200, 200, 700, 550)
        self.api_key = api_key
        self.base_url = base_url
        self.input_csv_path = None
        self.column_mapping_combos = {}
        self.worker = None
        self.thread = None

        self.initUI()
        self.prepare_language_list()
        self.load_settings()

    def prepare_language_list(self):
        # This map helps convert 2-letter Google codes to 3-letter IdoSell codes
        code_map_2_to_3 = {
            'pl': 'pol', 'en': 'eng', 'de': 'ger', 'cs': 'cze', 'sk': 'slo',
            'fr': 'fre', 'es': 'spa', 'it': 'ita', 'ro': 'rum', 'uk': 'ukr',
            'ru': 'rus', 'hu': 'hun', 'lt': 'lit', 'lv': 'lav', 'et': 'est',
            'bg': 'bul', 'el': 'gre', 'pt': 'por', 'nl': 'nld', 'da': 'dan',
            'fi': 'fin', 'sv': 'swe', 'no': 'nor', 'hr': 'hrv', 'sr': 'srp',
            'sl': 'slv'
        }
        
        preferred_codes = list(code_map_2_to_3.values())

        try:
            google_langs = GoogleTranslator().get_supported_languages(as_dict=True)
            all_codes = []
            for name, code_2_letter in sorted(google_langs.items(), key=lambda item: item[0]):
                code_3_letter = code_map_2_to_3.get(code_2_letter, code_2_letter)
                if code_3_letter not in all_codes:
                    all_codes.append(code_3_letter)
            
            final_list = preferred_codes + [code for code in all_codes if code not in preferred_codes]
            self.lang_id_combo.addItems(final_list)
            
        except Exception as e:
            self.log_message(f"Ostrzeżenie: Nie udało się pobrać pełnej listy języków z sieci: {e}")
            self.log_message("Używam rozszerzonej listy domyślnej.")
            fallback_list = [
                "pol", "eng", "ger", "cze", "slo", "fre", "spa", "ita",
                "rum", "ukr", "rus", "hun", "lit", "lav", "est", "bul", 
                "gre", "por", "nld", "dan", "fin", "swe", "nor", "hrv", 
                "srp", "slv"
            ]
            self.lang_id_combo.addItems(fallback_list)

        self.lang_id_combo.setCurrentText("eng")

    def initUI(self):
        main_layout = QVBoxLayout(self)

        # --- Krok 1: Ustawienia Główne ---
        settings_group = QGroupBox("Krok 1: Ustawienia Główne")
        settings_layout = QGridLayout()

        settings_layout.addWidget(QLabel("ID Sklepu (shopId):"), 0, 0)
        self.shop_id_input = QLineEdit("1")
        settings_layout.addWidget(self.shop_id_input, 0, 1)

        settings_layout.addWidget(QLabel("ID Języka (langId):"), 1, 0)
        self.lang_id_combo = QComboBox()
        # Items will be added by prepare_language_list
        settings_layout.addWidget(self.lang_id_combo, 1, 1)
        
        settings_layout.addWidget(QLabel("Rozmiar paczki (Batch Size):"), 2, 0)
        self.batch_size_spinbox = QSpinBox()
        self.batch_size_spinbox.setRange(1, 100)
        self.batch_size_spinbox.setValue(25)
        self.batch_size_spinbox.setToolTip("Liczba produktów aktualizowanych w jednym zapytaniu API. Zmniejsz w razie problemów.")
        settings_layout.addWidget(self.batch_size_spinbox, 2, 1)

        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # --- Krok 2: Plik i Mapowanie Pól ---
        mapping_group = QGroupBox("Krok 2: Plik i Mapowanie Pól")
        mapping_layout = QVBoxLayout()

        file_layout = QHBoxLayout()
        self.select_file_button = QPushButton("Wybierz plik CSV...")
        self.select_file_button.clicked.connect(self.select_input_file)
        self.selected_file_label = QLabel("Nie wybrano pliku")
        file_layout.addWidget(self.select_file_button)
        file_layout.addWidget(self.selected_file_label)
        file_layout.addStretch()
        mapping_layout.addLayout(file_layout)

        self.mapping_grid_layout = QGridLayout()
        self.mapping_fields = {
            "identValue": "ID Produktu",
            "productName": "Nazwa Produktu",
            "productLongDescription": "Opis Długi Produktu",
            "productDescription": "Opis Krótki Produktu"
        }

        for i, (field_key, field_label) in enumerate(self.mapping_fields.items()):
            label = QLabel(f"{field_label}:")
            combo = QComboBox()
            combo.setEnabled(False)
            self.mapping_grid_layout.addWidget(label, i, 0)
            self.mapping_grid_layout.addWidget(combo, i, 1)
            self.column_mapping_combos[field_key] = combo
        
        mapping_layout.addLayout(self.mapping_grid_layout)
        mapping_group.setLayout(mapping_layout)
        main_layout.addWidget(mapping_group)

        # --- Krok 3: Uruchomienie i Logi ---
        action_group = QGroupBox("Krok 3: Uruchomienie")
        action_layout = QVBoxLayout()

        start_stop_layout = QHBoxLayout()
        self.start_button = QPushButton("Rozpocznij aktualizację")
        self.start_button.clicked.connect(self.start_update)
        self.start_button.setEnabled(False)
        self.cancel_button = QPushButton("Anuluj")
        self.cancel_button.clicked.connect(self.cancel_update)
        self.cancel_button.hide()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.cancel_button)
        start_stop_layout.addStretch()
        action_layout.addLayout(start_stop_layout)

        self.progress_bar = QProgressBar()
        action_layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        action_layout.addWidget(QLabel("Logi:"))
        action_layout.addWidget(self.log_output)
        
        action_group.setLayout(action_layout)
        main_layout.addWidget(action_group)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.controls_to_toggle = [
            self.select_file_button, self.shop_id_input,
            self.lang_id_combo, self.batch_size_spinbox
        ]
        for combo in self.column_mapping_combos.values():
            self.controls_to_toggle.append(combo)

    def start_update(self):
        if not self.input_csv_path:
            QMessageBox.critical(self, "Błąd", "Najpierw wybierz plik CSV!")
            return
            
        try:
            shop_id = int(self.shop_id_input.text().strip())
        except ValueError:
            QMessageBox.critical(self, "Błąd", "ID Sklepu musi być liczbą całkowitą!")
            return

        column_map = {key: combo.currentText() for key, combo in self.column_mapping_combos.items()}
        if any(not value for value in column_map.values()):
            QMessageBox.critical(self, "Błąd", "Wszystkie pola muszą być zmapowane na kolumny z pliku CSV!")
            return

        self.save_settings()
        self.toggle_controls(False)
        self.log_output.clear()
        self.progress_bar.setValue(0)

        self.thread = QThread()
        self.worker = DescriptionUpdaterWorker(
            file_path=self.input_csv_path,
            api_key=self.api_key,
            base_url=self.base_url,
            shop_id=shop_id,
            lang_id=self.lang_id_combo.currentText(),
            batch_size=self.batch_size_spinbox.value(),
            column_map=column_map
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.task_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.worker.log_message.connect(self.log_message)
        self.worker.progress.connect(self.update_progress)

        self.thread.start()

    def cancel_update(self):
        if self.worker:
            self.log_message("Wysyłanie prośby o anulowanie...")
            self.worker.cancel()
            self.cancel_button.setEnabled(False)

    def task_finished(self, message):
        self.log_message(f"Zakończono z komunikatem: {message}")
        QMessageBox.information(self, "Koniec", f"Proces aktualizacji zakończony.\nStatus: {message}")
        self.toggle_controls(True)
        self.worker = None
        self.thread = None

    def update_progress(self, value, total, message):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(value)

    def toggle_controls(self, enabled):
        for control in self.controls_to_toggle:
            control.setEnabled(enabled)
        self.start_button.setHidden(not enabled)
        self.cancel_button.setHidden(enabled)
        if enabled:
            self.cancel_button.setEnabled(True)

    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz plik CSV z tłumaczeniami", "", "CSV Files (*.csv)")
        if path:
            self.input_csv_path = path
            self.selected_file_label.setText(os.path.basename(path))
            self.log_message(f"Wybrano plik: {path}")
            self.load_columns_from_csv()

    def load_columns_from_csv(self):
        if not self.input_csv_path:
            return
        try:
            df_columns = pd.read_csv(self.input_csv_path, nrows=0, on_bad_lines='skip').columns.tolist()
            self.log_message(f"Wczytano kolumny: {df_columns}")
            for field_key, combo in self.column_mapping_combos.items():
                combo.clear()
                combo.addItems(df_columns)
                combo.setEnabled(True)
            self.start_button.setEnabled(True)
            self.load_settings() # Reload settings to apply saved mappings
        except Exception as e:
            QMessageBox.critical(self, "Błąd", f"Nie można wczytać kolumn z pliku CSV: {e}")
            self.start_button.setEnabled(False)

    def log_message(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {msg}")

    def save_settings(self):
        settings = QSettings("IdoKombajn", "DescriptionUpdater")
        settings.setValue("shop_id", self.shop_id_input.text())
        settings.setValue("lang_id", self.lang_id_combo.currentText())
        settings.setValue("batch_size", self.batch_size_spinbox.value())
        if self.input_csv_path:
            settings.setValue("last_csv_path", self.input_csv_path)
        for key, combo in self.column_mapping_combos.items():
            if combo.isEnabled():
                settings.setValue(f"map_{key}", combo.currentText())

    def load_settings(self):
        settings = QSettings("IdoKombajn", "DescriptionUpdater")
        self.shop_id_input.setText(settings.value("shop_id", "1"))
        self.lang_id_combo.setCurrentText(settings.value("lang_id", "eng"))
        self.batch_size_spinbox.setValue(int(settings.value("batch_size", 25)))
        
        last_path = settings.value("last_csv_path", "")
        if last_path and os.path.exists(last_path) and not self.input_csv_path:
            self.input_csv_path = last_path
            self.selected_file_label.setText(os.path.basename(last_path))
            self.load_columns_from_csv()
        
        # Restore last mapping after columns are loaded
        for key, combo in self.column_mapping_combos.items():
            if combo.count() > 0:
                saved_col = settings.value(f"map_{key}", "")
                if saved_col:
                    combo.setCurrentText(saved_col)

    def reject(self):
        if self.worker:
            self.worker.cancel()
        self.save_settings()
        super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
        self.save_settings()
        super().closeEvent(event)
