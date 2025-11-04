
import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, 
    QTextEdit, QProgressBar, QLabel, QFileDialog, QCheckBox,
    QMessageBox, QDialogButtonBox, QGroupBox, QColorDialog
)
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor
import os
import time
import re

from logic.description_generator import run_description_generator

class DescriptionGeneratorWorker(QObject):
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str, float)

    def __init__(self, api_key, input_path, prompt, use_html_frame, frame_color, id_column, desc_column):
        super().__init__()
        self.api_key = api_key
        self.input_path = input_path
        self.prompt = prompt
        self.use_html_frame = use_html_frame
        self.frame_color = frame_color
        self.id_column = id_column
        self.desc_column = desc_column
        self.is_running = True # This can be used in the future to stop the process

    def run(self):
        start_time = time.time()
        final_path = ""
        try:
            final_path = run_description_generator(
                self.api_key, self.input_path, self.prompt, self.use_html_frame, 
                self.frame_color, self.id_column, self.desc_column, 
                self.log_message.emit, lambda: not self.is_running
            )
        except Exception as e:
            self.log_message.emit(f"Wystąpił krytyczny błąd w wątku: {e}")
        finally:
            total_time = time.time() - start_time
            self.finished.emit(final_path if final_path else "", total_time)

    def stop(self):
        self.is_running = False

class DescriptionGeneratorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generator Opisów AI (OpenAI)")
        self.setGeometry(150, 150, 800, 700)
        self.input_csv_path = None
        self.worker = None
        self.thread = None

        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)

        # Krok 1: Konfiguracja API i Pliku
        config_group_box = QGroupBox("Krok 1: Konfiguracja")
        config_layout = QVBoxLayout()
        
        api_layout = QHBoxLayout()
        api_layout.addWidget(QLabel("Klucz API OpenAI:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addWidget(self.api_key_input)
        config_layout.addLayout(api_layout)

        file_layout = QHBoxLayout()
        self.select_file_button = QPushButton("Wybierz plik wejściowy (.csv)...")
        self.select_file_button.clicked.connect(self.select_input_file)
        self.selected_file_label = QLabel("Nie wybrano pliku")
        file_layout.addWidget(self.select_file_button)
        file_layout.addWidget(self.selected_file_label)
        file_layout.addStretch()
        config_layout.addLayout(file_layout)
        
        config_group_box.setLayout(config_layout)
        main_layout.addWidget(config_group_box)

        # Krok 2: Konfiguracja Kolumn
        columns_group_box = QGroupBox("Krok 2: Konfiguracja Kolumn")
        columns_layout = QHBoxLayout()
        columns_layout.addWidget(QLabel("Kolumna ID Produktu:"))
        self.id_column_input = QLineEdit("@id")
        columns_layout.addWidget(self.id_column_input)
        columns_layout.addWidget(QLabel("Kolumna z opisem do analizy:"))
        self.description_column_input = QLineEdit("/description/long_desc[pol]")
        columns_layout.addWidget(self.description_column_input)
        columns_group_box.setLayout(columns_layout)
        main_layout.addWidget(columns_group_box)


        # Krok 3: Prompt
        prompt_group_box = QGroupBox("Krok 3: Prompt dla AI")
        prompt_layout = QVBoxLayout()
        self.prompt_input = QTextEdit()
        example_prompt = """Jesteś copywriterem premium dla branży erotycznej. Otrzymujesz cechy produktu. Stwórz 4 elementy i zwróć je w formacie JSON: "nazwa_produktu" (chwytliwa, 2-4 słowa), "zajawka" (1-2 zdania), "opis_glowny" (3-4 zdania, sensualny), "cechy_marketingowe" (lista cech w języku korzyści). Cechy wejściowe: {features_str}. Zwróć tylko JSON."""
        self.prompt_input.setText(example_prompt)
        prompt_layout.addWidget(self.prompt_input)
        prompt_group_box.setLayout(prompt_layout)
        main_layout.addWidget(prompt_group_box)

        # Krok 3: Opcje formatowania
        format_group_box = QGroupBox("Krok 3: Formatowanie Wyjścia")
        format_layout = QHBoxLayout()
        self.html_frame_checkbox = QCheckBox("Dodaj ramkę HTML do opisu")
        self.html_frame_checkbox.setChecked(True)
        self.html_frame_checkbox.toggled.connect(self.toggle_color_button)
        format_layout.addWidget(self.html_frame_checkbox)

        self.color_button = QPushButton("Wybierz kolor ramki")
        self.color_button.clicked.connect(self.select_color)
        self.selected_color = QColor("#f45844")
        self.color_button.setStyleSheet(f"background-color: {self.selected_color.name()};")
        format_layout.addWidget(self.color_button)
        format_layout.addStretch()
        format_group_box.setLayout(format_layout)
        main_layout.addWidget(format_group_box)

        # Start / Stop
        self.start_button = QPushButton("Rozpocznij generowanie")
        self.start_button.clicked.connect(self.start_generation)
        self.stop_button = QPushButton("Zatrzymaj")
        self.stop_button.clicked.connect(self.request_stop) # Non-blocking stop
        self.stop_button.setEnabled(False)
        
        start_stop_layout = QHBoxLayout()
        start_stop_layout.addWidget(self.start_button)
        start_stop_layout.addWidget(self.stop_button)
        main_layout.addLayout(start_stop_layout)

        # Postęp i status
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%v / %m")
        main_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Oczekiwanie na konfigurację...")
        main_layout.addWidget(self.status_label)

        # Logi
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(QLabel("Logi:"))
        main_layout.addWidget(self.log_output)

        # Przyciski
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz plik CSV", "", "CSV Files (*.csv);;All Files (*)")
        if path:
            self.input_csv_path = path
            self.selected_file_label.setText(os.path.basename(path))
            self.log_message(f"Wybrano plik: {path}")


    def toggle_color_button(self, checked):
        self.color_button.setEnabled(checked)

    def select_color(self):
        color = QColorDialog.getColor(self.selected_color, self)
        if color.isValid():
            self.selected_color = color
            self.color_button.setStyleSheet(f"background-color: {self.selected_color.name()};")

    def start_generation(self):
        api_key = self.api_key_input.text()
        if not api_key:
            QMessageBox.critical(self, "Błąd", "Klucz API OpenAI jest wymagany!")
            return
        
        if not self.input_csv_path:
            QMessageBox.critical(self, "Błąd", "Wybierz plik wejściowy CSV!")
            return

        id_column = self.id_column_input.text()
        desc_column = self.description_column_input.text()
        if not id_column or not desc_column:
            QMessageBox.critical(self, "Błąd", "Nazwy kolumn nie mogą być puste!")
            return

        prompt = self.prompt_input.toPlainText()
        use_html_frame = self.html_frame_checkbox.isChecked()
        frame_color = self.selected_color.name()

        self.toggle_controls(False)

        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("Rozpoczynanie...")
        
        self.thread = QThread()
        self.worker = DescriptionGeneratorWorker(
            api_key, self.input_csv_path, prompt, use_html_frame, 
            frame_color, id_column, desc_column
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_message.connect(self.log_message)
        self.worker.finished.connect(self.task_finished)
        
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def request_stop(self):
        if self.worker and self.thread and self.thread.isRunning():
            self.log_message("Wysłano prośbę o zatrzymanie. Proces zakończy się po ukończeniu bieżącej operacji.")
            self.worker.is_running = False
            self.status_label.setText("Zatrzymywanie...")
            self.stop_button.setEnabled(False) # Prevent multiple clicks

    def toggle_controls(self, enabled):
        self.start_button.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)
        self.api_key_input.setEnabled(enabled)
        self.select_file_button.setEnabled(enabled)
        self.prompt_input.setEnabled(enabled)
        self.html_frame_checkbox.setEnabled(enabled)
        self.color_button.setEnabled(enabled and self.html_frame_checkbox.isChecked())
        self.id_column_input.setEnabled(enabled)
        self.description_column_input.setEnabled(enabled)

    def log_message(self, message):
        timestamp = time.strftime("%H:%M:%S")
        
        progress_match = re.match(r"\((\d+)/(\d+)\)", message)
        if progress_match:
            current, total = int(progress_match.group(1)), int(progress_match.group(2))
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.status_label.setText(f"Przetwarzanie: {current}/{total}")

        if "BŁĄD" in message or "krytyczny" in message.lower() or "error" in message.lower():
            self.log_output.append(f'<font color="#FF5555">[{timestamp}] {message}</font>')
        elif "ostrzeżenie" in message.lower() or "warning" in message.lower():
            self.log_output.append(f'<font color="#F9A602">[{timestamp}] {message}</font>')
        elif "sukces" in message.lower() or "ukończono" in message.lower() or "zakończono" in message.lower():
            self.log_output.append(f'<font color="#50C878">[{timestamp}] {message}</font>')
        else:
            self.log_output.append(f"[{timestamp}] {message}")

    def task_finished(self, output_path, total_time):
        if not self.worker.is_running: # If task was stopped by user
            self.log_message("Zadanie przerwane przez użytkownika.")
            self.status_label.setText("Zatrzymano.")
        elif output_path:
            self.log_message(f"--- ZAKOŃCZONO ---")
            self.log_message(f"Wyniki zapisano w '{output_path}'.")
            self.status_label.setText(f"Zakończono! Czas: {total_time:.2f}s.")
        else:
            self.log_message("Zadanie zakończone z błędem lub bez wygenerowania pliku.")
            self.status_label.setText("Zakończono z błędem.")
        
        self.toggle_controls(True)
        if self.isHidden():
            self.accept()

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            reply = QMessageBox.question(self, 'Zadanie w toku', 
                                     "Generator opisów wciąż pracuje. Czy na pewno chcesz go zatrzymać i zamknąć okno?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                self.request_stop()
                self.status_label.setText("Zamykanie po zakończeniu zadania...")
                self.hide()
                event.ignore()
            else:
                event.ignore()
        else:
            event.accept()
