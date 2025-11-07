
import os
import time
import pandas as pd
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLineEdit, 
    QTextEdit, QProgressBar, QLabel, QFileDialog, QGroupBox, QMessageBox, 
    QDialogButtonBox, QSpinBox, QFormLayout
)
from PyQt6.QtCore import QThread, pyqtSignal

from logic.attribute_translator import run_attribute_translator

class Worker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, input_path, id_column, desc_column, lang, batch_size):
        super().__init__()
        self.input_path = input_path
        self.id_column = id_column
        self.desc_column = desc_column
        self.lang = lang
        self.batch_size = batch_size

    def run(self):
        result = run_attribute_translator(
            self.input_path, 
            self.id_column, 
            self.desc_column, 
            self.lang, 
            1, # num_workers is not used anymore
            self.batch_size,
            lambda msg: self.progress.emit(msg)
        )
        self.finished.emit(result)

from deep_translator import GoogleTranslator

class AttributeTranslatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tłumacz Atrybutów ALT/TITLE")
        self.setGeometry(200, 200, 700, 600)
        self.input_csv_path = None
        self.worker_thread = None

        self.initUI()
        self.prepare_language_list()

    def initUI(self):
        main_layout = QVBoxLayout(self)

        # Krok 1: Wybór pliku
        file_group = QGroupBox("Krok 1: Wybór Pliku")
        file_layout = QHBoxLayout()
        self.select_file_button = QPushButton("Wybierz plik .csv...")
        self.select_file_button.clicked.connect(self.select_input_file)
        self.selected_file_label = QLabel("Nie wybrano pliku")
        file_layout.addWidget(self.select_file_button)
        file_layout.addWidget(self.selected_file_label)
        file_layout.addStretch()
        file_group.setLayout(file_layout)
        main_layout.addWidget(file_group)

        # Krok 2: Ustawienia
        settings_group = QGroupBox("Krok 2: Ustawienia")
        settings_layout = QFormLayout()
        self.id_column_combo = QComboBox()
        self.description_column_combo = QComboBox()
        self.target_lang_combo = QComboBox()
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setValue(20)
        self.batch_size_input.setMinimum(1)
        self.batch_size_input.setMaximum(200)

        settings_layout.addRow("Kolumna z ID Produktu:", self.id_column_combo)
        settings_layout.addRow("Kolumna z opisem HTML:", self.description_column_combo)
        settings_layout.addRow("Język docelowy:", self.target_lang_combo)
        settings_layout.addRow("Rozmiar paczki (Batch Size):", self.batch_size_input)
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # Start
        self.start_button = QPushButton("Rozpocznij tłumaczenie atrybutów")
        self.start_button.clicked.connect(self.start_task)
        self.start_button.setEnabled(False)
        main_layout.addWidget(self.start_button)

        # Postęp i Logi
        self.progress_bar = QProgressBar()
        self.status_label = QLabel("Oczekiwanie na zadanie...")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(QLabel("Logi:"))
        main_layout.addWidget(self.log_output)

        # Przyciski
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def prepare_language_list(self):
        try:
            full_lang_list = GoogleTranslator().get_supported_languages(as_dict=True)
            self.language_map_code_to_name = {code: name.capitalize() for name, code in full_lang_list.items()}
            preferred_languages = {"Polski": "pl", "Angielski": "en", "Niemiecki": "de", "Francuski": "fr", "Hiszpański": "es", "Włoski": "it", "Czeski": "cs", "Słowacki": "sk", "Ukraiński": "uk", "Rosyjski": "ru"}
            self.language_map_display = preferred_languages.copy()
            for code, name in sorted(self.language_map_code_to_name.items(), key=lambda item: item[1]):
                if code not in preferred_languages.values(): self.language_map_display[name] = code
            
            self.target_lang_combo.addItems(self.language_map_display.keys())
            self.target_lang_combo.setCurrentText("Angielski")
        except Exception as e:
            self.language_map_display = {"Polski": "pl", "Angielski": "en", "Niemiecki": "de"}
            QMessageBox.warning(self, "Błąd sieci", f"Nie udało się pobrać pełnej listy języków: {e}\nUżywana jest lista podstawowa.")

    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz plik CSV", "", "CSV Files (*.csv)")
        if path:
            self.input_csv_path = path
            self.selected_file_label.setText(os.path.basename(path))
            self.log_message(f"Wybrano plik: {path}")
            self.load_columns()
            self.start_button.setEnabled(True)

    def load_columns(self):
        try:
            df_columns = pd.read_csv(self.input_csv_path, nrows=0).columns.tolist()
            self.id_column_combo.clear()
            self.description_column_combo.clear()
            self.id_column_combo.addItems(df_columns)
            self.description_column_combo.addItems(df_columns)
            self.log_message(f"Wczytano kolumny: {df_columns}")
        except Exception as e:
            QMessageBox.critical(self, "Błąd", f"Nie można wczytać kolumn z pliku: {e}")

    def start_task(self):
        if not self.input_csv_path:
            QMessageBox.warning(self, "Uwaga", "Najpierw wybierz plik CSV.")
            return

        id_col = self.id_column_combo.currentText()
        desc_col = self.description_column_combo.currentText()
        lang_name = self.target_lang_combo.currentText()
        lang_code = self.language_map_display[lang_name]
        batch_size = self.batch_size_input.value()

        if not id_col or not desc_col:
            QMessageBox.warning(self, "Uwaga", "Wybierz kolumnę z ID i kolumnę z opisem.")
            return

        self.start_button.setEnabled(False)
        self.log_output.clear()
        self.log_message("--- Rozpoczynam tłumaczenie atrybutów ---")
        
        self.worker_thread = Worker(self.input_csv_path, id_col, desc_col, lang_code, batch_size)
        self.worker_thread.progress.connect(self.log_message)
        self.worker_thread.finished.connect(self.task_finished)
        self.worker_thread.start()

    def log_message(self, message):
        self.log_output.append(message)
        if message.startswith("Etap 1/4"):
            self.progress_bar.setValue(0)
            self.status_label.setText("Etap 1: Wczytywanie...")
        elif message.startswith("Etap 2/4"):
            self.progress_bar.setValue(0)
            self.status_label.setText("Etap 2: Tłumaczenie...")
        elif message.startswith("Etap 3/4"):
            self.progress_bar.setValue(100)
            self.status_label.setText("Etap 3: Aktualizowanie opisów...")
        elif message.startswith("Etap 4/4"):
            self.progress_bar.setValue(100)
            self.status_label.setText("Etap 4: Zapisywanie...")
        elif "Przetłumaczono" in message and "tekstów" in message:
            try:
                # Find numbers in the string, e.g., "Przetłumaczono 100/208 tekstów..."
                numbers = [int(s) for s in re.findall(r'\d+', message)]
                if len(numbers) == 2:
                    current, total = numbers
                    self.progress_bar.setMaximum(total)
                    self.progress_bar.setValue(current)
                    self.status_label.setText(f"Etap 2: Tłumaczenie... {current}/{total}")
            except (ValueError, IndexError):
                pass

    def task_finished(self, result):
        self.log_message(f"--- Zakończono ---: {result}")
        self.status_label.setText("Zadanie zakończone.")
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.start_button.setEnabled(True)
        QMessageBox.information(self, "Sukces", f"Przetwarzanie zakończone!\n{result}")

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, 'Zamykanie', 
                                       "Proces wciąż działa. Czy na pewno chcesz go przerwać i zamknąć okno?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.worker_thread.quit()
                self.worker_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
