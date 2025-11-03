
import pandas as pd
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
import time
import threading
from collections import deque
import math
import re
import os
import random
import logging
import requests
import io

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLineEdit, 
    QTextEdit, QProgressBar, QLabel, QFileDialog, QCheckBox,
    QMessageBox, QDialogButtonBox, QGroupBox
)
from PyQt6.QtCore import QThread, pyqtSignal, QObject

# --- Konfiguracja ---
ID_COLUMN = 'ID'
ACTIVATE_COOLDOWN_AFTER_RETRIES = 2
GLOBAL_COOLDOWN_MINUTES = 15

class RateLimiter:
    def __init__(self, requests_per_second):
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else float('inf')
        self.lock = threading.Lock()
        self.last_request_time = time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_request_time
            if elapsed > 10:
                self.last_request_time = now - self.min_interval
                elapsed = self.min_interval
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_request_time = time.monotonic()

class TranslationWorker(QObject):
    progress = pyqtSignal(int)
    log_info = pyqtSignal(str)
    log_error = pyqtSignal(str)
    update_status = pyqtSignal(str)
    finished = pyqtSignal(str, float)
    cooldown_started = pyqtSignal(int)
    cooldown_finished = pyqtSignal()

    def __init__(self, parent_dialog, source_lang, target_lang, columns_to_translate, num_workers, requests_per_sec, input_csv_path, is_diagnostic_mode):
        super().__init__()
        self.d = parent_dialog
        self.global_cooldown_lock = threading.Lock()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.columns_to_translate = columns_to_translate
        self.num_workers = num_workers
        self.requests_per_sec = requests_per_sec
        self.input_csv_path = input_csv_path
        self.is_diagnostic_mode = is_diagnostic_mode

    def translation_worker_thread(self, worker_id, chunks, source, target, limiter, results):
        self.log_info.emit(f"[Wątek {worker_id}] Start: {len(chunks)} fragmentów.")
        translated, translator = [], GoogleTranslator(source=source, target=target)
        batch, chars, total, processed = [], 0, len(chunks), 0
        chunk_idx = 0
        while chunk_idx < len(chunks):
            chunk = chunks[chunk_idx]
            if not chunk or not chunk.strip():
                batch.append(' ')
                chunk_idx += 1
                continue

            if chars + len(chunk) > 4800 and batch:
                pass
            else:
                batch.append(chunk)
                chars += len(chunk)
                chunk_idx += 1
            
            if chunk_idx < len(chunks) and (chars + len(chunks[chunk_idx]) <= 4800):
                continue

            is_successful, retries = False, 0
            while not is_successful:
                with self.global_cooldown_lock:
                    pass

                limiter.wait()
                try:
                    t_batch = translator.translate_batch(batch)
                    safe_t_batch = [t if t is not None else o for o, t in zip(batch, t_batch)]
                    translated.extend(safe_t_batch)
                    processed += len(batch)
                    self.log_info.emit(f"[Wątek {worker_id}] OK: {len(batch)} frag. ({processed}/{total})")
                    is_successful = True
                except Exception as e:
                    if "too many requests" in str(e).lower():
                        retries += 1
                        if retries >= ACTIVATE_COOLDOWN_AFTER_RETRIES:
                            if self.global_cooldown_lock.acquire(blocking=False):
                                self.log_error.emit(f"!!! ZDALNY BAN! [Lider: {worker_id}] rozpoczyna procedurę.")
                                cooldown_seconds = GLOBAL_COOLDOWN_MINUTES * 60
                                self.cooldown_started.emit(cooldown_seconds)
                                time.sleep(cooldown_seconds)
                                self.cooldown_finished.emit()
                                self.global_cooldown_lock.release()
                            else:
                                self.log_info.emit(f"[Wątek {worker_id}] Inny wątek jest Liderem. Czekam...")
                            retries = 0
                        else:
                            delay = 2 * (2 ** retries) + random.uniform(0, 1)
                            self.log_error.emit(f"[Wątek {worker_id}] LIMIT! Próba {retries}. Czekam {delay:.1f}s...")
                            time.sleep(delay)
                    else:
                        self.log_error.emit(f"[Wątek {worker_id}] BŁĄD KRYTYCZNY: {e}. Używam oryginałów.")
                        translated.extend(batch)
                        is_successful = True
            
            self.progress.emit(len(batch))
            batch, chars = [], 0
        results[worker_id] = translated
        self.log_info.emit(f"[Wątek {worker_id}] Koniec.")

    def run(self):
        start_time = time.time()
        skipped_cells_report = []
        try:
            self.log_info.emit(f"--- Start tłumaczenia z '{self.source_lang.upper()}' na '{self.target_lang.upper()}' ---")
            if self.is_diagnostic_mode:
                self.log_info.emit("Tryb diagnostyczny jest włączony. Generowanie raportu pominiętych komórek.")

            df = pd.read_csv(self.input_csv_path, on_bad_lines='skip').fillna('')
            
            cells_to_process = []
            all_texts_to_translate = []
            whitespace_map = []

            for col in self.columns_to_translate:
                if col not in df.columns: continue
                for i, cell_content in enumerate(df[col]):
                    original_content = cell_content
                    cell_content_str = str(cell_content)

                    if not cell_content_str.strip():
                        if self.is_diagnostic_mode:
                            skipped_cells_report.append({
                                'Wiersz': i + 2,
                                'Kolumna': col,
                                'Powód': 'Komórka jest pusta lub zawiera tylko białe znaki',
                                'Zawartość': original_content
                            })
                        continue

                    texts_for_this_cell = []
                    soup = BeautifulSoup(cell_content_str, "html.parser")
                    nodes_to_process = soup.find_all(string=True)
                    
                    for node in nodes_to_process:
                        if node.parent.name in ['style', 'script', 'head', 'title', 'meta']:
                            continue
                        if node.strip():
                            text = str(node)
                            has_leading = text.startswith(' ')
                            has_trailing = text.endswith(' ')
                            whitespace_map.append({'leading': has_leading, 'trailing': has_trailing})
                            texts_for_this_cell.append(text.strip())

                    if texts_for_this_cell:
                        # Determine if the original was HTML for reconstruction purposes
                        is_html = bool(BeautifulSoup(original_content, "html.parser").find())
                        cells_to_process.append({'loc': (i, col), 'is_html': is_html, 'count': len(texts_for_this_cell)})
                        all_texts_to_translate.extend(texts_for_this_cell)
                    elif self.is_diagnostic_mode:
                        skipped_cells_report.append({
                            'Wiersz': i + 2,
                            'Kolumna': col,
                            'Powód': 'Brak tekstu do tłumaczenia (np. tylko puste tagi HTML)',
                            'Zawartość': original_content
                        })

            if not all_texts_to_translate:
                self.log_info.emit("Nie znaleziono żadnych tekstów do tłumaczenia we wszystkich wybranych komórkach.")
                if self.is_diagnostic_mode and skipped_cells_report:
                    # Save report even if no texts were found to translate
                    report_df = pd.DataFrame(skipped_cells_report)
                    report_path = os.path.join(os.path.dirname(self.input_csv_path), "raport_pominietych_komorek.csv")
                    report_df.to_csv(report_path, index=False, encoding='utf-8-sig')
                    self.log_info.emit(f"Wygenerowano raport pominiętych komórek: {report_path}")
                self.finished.emit("", 0)
                return

            self.d.total_chunks_to_process = len(all_texts_to_translate)
            self.log_info.emit(f"Znaleziono {len(cells_to_process)} komórek zawierających tekst, łącznie {self.d.total_chunks_to_process} fragmentów do tłumaczenia.")
            
            limiter = RateLimiter(self.requests_per_sec)
            chunk_split = math.ceil(len(all_texts_to_translate) / self.num_workers) if self.num_workers > 0 else len(all_texts_to_translate)
            chunk_groups = [all_texts_to_translate[i:i + chunk_split] for i in range(0, len(all_texts_to_translate), chunk_split)]

            threads, results = [], [[] for _ in chunk_groups]
            for i, group in enumerate(chunk_groups):
                thread = threading.Thread(target=self.translation_worker_thread, args=(i, group, self.source_lang, self.target_lang, limiter, results))
                threads.append(thread)
                thread.start()
            
            for thread in threads: thread.join()
            
            translated_texts_stripped = [chunk for res_list in results for chunk in res_list]
            
            translated_texts = []
            for i, text in enumerate(translated_texts_stripped):
                if i < len(whitespace_map):
                    ws_info = whitespace_map[i]
                    restored_text = text
                    if ws_info['leading']: restored_text = ' ' + restored_text
                    if ws_info['trailing']: restored_text = restored_text + ' '
                    translated_texts.append(restored_text)
                else:
                    translated_texts.append(text) # Fallback

            text_ptr = 0
            for cell_info in cells_to_process:
                translated_parts = translated_texts[text_ptr : text_ptr + cell_info['count']]
                text_ptr += cell_info['count']
                
                if cell_info['is_html']:
                    # Use original content to reconstruct, not df.at, which might be a different type
                    original_cell_content = str(df.iloc[cell_info['loc'][0]][cell_info['loc'][1]])
                    soup = BeautifulSoup(original_cell_content, "html.parser")
                    nodes_to_replace = [node for node in soup.find_all(string=True) if node.parent.name not in ['style', 'script', 'head', 'title', 'meta'] and node.strip()]
                    
                    for i, node in enumerate(nodes_to_replace):
                        if i < len(translated_parts):
                            node.replace_with(translated_parts[i])

                    df.at[cell_info['loc']] = str(soup)
                else:
                    df.at[cell_info['loc']] = "".join(translated_parts)

            base, ext = os.path.splitext(os.path.basename(self.input_csv_path))
            output_path = os.path.join(os.path.dirname(self.input_csv_path), f"{base}_translated{ext}")
            df.to_csv(output_path, index=False, encoding='utf-8')
            
            if self.is_diagnostic_mode and skipped_cells_report:
                report_df = pd.DataFrame(skipped_cells_report)
                report_path = os.path.join(os.path.dirname(self.input_csv_path), "raport_pominietych_komorek.csv")
                report_df.to_csv(report_path, index=False, encoding='utf-8-sig')
                self.log_info.emit(f"Wygenerowano raport pominiętych komórek: {report_path}")

            total_time = time.time() - start_time
            self.finished.emit(output_path, total_time)

        except Exception as e:
            self.log_error.emit(f"BŁĄD KRYTYCZNY w głównym wątku: {e}")
            import traceback
            self.log_error.emit(traceback.format_exc())



class TranslatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tłumacz Google")
        self.setGeometry(150, 150, 800, 700)
        self.input_csv_path = None
        self.column_vars = {}
        self.total_chunks_processed = 0
        self.total_chunks_to_process = 0
        self.start_time = 0
        self.is_cooldown = False

        self.initUI()
        self.prepare_language_list()

    def initUI(self):
        main_layout = QVBoxLayout(self)

        # Krok 1: Wybór pliku
        file_group_box = QGroupBox("Krok 1: Wybór Pliku")
        file_layout = QHBoxLayout()
        self.select_file_button = QPushButton("Wybierz plik wejściowy (.csv)...")
        self.select_file_button.clicked.connect(self.select_input_file)
        self.selected_file_label = QLabel("Nie wybrano pliku")
        file_layout.addWidget(self.select_file_button)
        file_layout.addWidget(self.selected_file_label)
        file_layout.addStretch()
        file_group_box.setLayout(file_layout)
        main_layout.addWidget(file_group_box)

        # Krok 2: Ustawienia
        settings_group_box = QGroupBox("Krok 2: Ustawienia Tłumaczenia")
        settings_layout = QVBoxLayout()
        
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Język źródłowy:"))
        self.source_lang_combo = QComboBox()
        lang_layout.addWidget(self.source_lang_combo)
        lang_layout.addWidget(QLabel("Język docelowy:"))
        self.target_lang_combo = QComboBox()
        lang_layout.addWidget(self.target_lang_combo)
        settings_layout.addLayout(lang_layout)

        adv_layout = QVBoxLayout()

        threads_layout = QHBoxLayout()
        threads_layout.addWidget(QLabel("Liczba wątków:"))
        self.num_workers_input = QLineEdit("3")
        threads_layout.addWidget(self.num_workers_input)
        threads_info_label = QLabel("ⓘ")
        threads_info_label.setToolTip("Liczba 'pracowników', na których podzielona zostanie praca z plikiem.\nPrzy dużych plikach zalecam 2, natomiast przy mniejszych można próbować 4.")
        threads_layout.addWidget(threads_info_label)
        threads_layout.addStretch()

        req_layout = QHBoxLayout()
        req_layout.addWidget(QLabel("Max zapytań/sek:"))
        self.requests_per_sec_input = QLineEdit("3.0")
        req_layout.addWidget(self.requests_per_sec_input)
        req_info_label = QLabel("ⓘ")
        req_info_label.setToolTip("Nieoficjalnie Google przyjmuje maksymalnie 5 zapytań na sekundę,\njednak z mojego doświadczenia wynika, że wtedy szybko zostaniemy\nzbanowani na 30 minut. Przy dużych plikach zalecam wartość 3,\nprzy mniejszych można próbować np. 4 lub 4.5.")
        req_layout.addWidget(req_info_label)
        req_layout.addStretch()

        adv_layout.addLayout(threads_layout)
        adv_layout.addLayout(req_layout)
        settings_layout.addLayout(adv_layout)

        self.diagnostic_checkbox = QCheckBox("Uruchom w trybie diagnostycznym (generuj raport pominiętych komórek)")
        settings_layout.addWidget(self.diagnostic_checkbox)
        
        settings_group_box.setLayout(settings_layout)
        main_layout.addWidget(settings_group_box)

        # Krok 3: Wybór kolumn
        columns_group_box = QGroupBox("Krok 3: Wybór Kolumn")
        columns_main_layout = QVBoxLayout()
        self.load_columns_button = QPushButton("Wczytaj kolumny z pliku")
        self.load_columns_button.setEnabled(False)
        self.load_columns_button.clicked.connect(self.load_columns_from_csv)
        columns_main_layout.addWidget(self.load_columns_button)
        self.column_checkbox_layout = QVBoxLayout()
        columns_main_layout.addLayout(self.column_checkbox_layout)
        columns_main_layout.addStretch()
        columns_group_box.setLayout(columns_main_layout)
        main_layout.addWidget(columns_group_box)

        # Start
        start_layout = QHBoxLayout()
        self.start_button = QPushButton("Rozpocznij tłumaczenie")
        self.start_button.clicked.connect(self.start_translation)
        
        info_label = QLabel("ⓘ")
        info_label.setToolTip(
            """<h3>Jak działa tłumacz?</h3>
            <p>Proces jest podzielony na 4 główne kroki:</p>
            <ol>
                <li><b>Przygotowanie:</b> Po wybraniu pliku, kolumn i ustawień, aplikacja tworzy w tle "pracownika", który zajmie się tłumaczeniem, nie blokując interfejsu.</li>
                <li><b>Ekstrakcja tekstu:</b>
                    <ul>
                        <li>Pracownik analizuje każdą wybraną komórkę w pliku CSV.</li>
                        <li><b>Inteligentnie rozpoznaje HTML:</b> Używa specjalistycznej biblioteki do analizy kodu HTML, aby wyodrębnić tylko tekst widoczny dla użytkownika (wewnątrz tagów jak &lt;p&gt;, &lt;h1&gt;, itp.) oraz tekst z ważnych atrybutów (np. 'alt' w obrazkach). Struktura HTML pozostaje nienaruszona.</li>
                        <li><b>Ignoruje kod:</b> Zawartość tagów &lt;style&gt; i &lt;script&gt; jest celowo pomijana, aby nie zniszczyć wyglądu strony.</li>
                        <li><b>Ochrona spacji:</b> Skrypt zapamiętuje, czy fragment tekstu (np. przy tagu &lt;strong&gt;) miał spację na początku lub na końcu.</li>
                    </ul>
                </li>
                <li><b>Tłumaczenie równoległe:</b>
                    <ul>
                        <li>Wszystkie zebrane teksty (już bez "chronionych" spacji) są dzielone na paczki i wysyłane do tłumaczenia w wielu wątkach jednocześnie (zgodnie z Twoimi ustawieniami).</li>
                        <li><b>Ochrona przed banem:</b> Specjalny "hamulec" pilnuje, aby nie wysłać zbyt wielu zapytań na sekundę. W razie tymczasowej blokady od Google, proces jest automatycznie wstrzymywany na 15 minut i wznawiany.</li>
                    </ul>
                </li>
                <li><b>Składanie i zapis:</b>
                    <ul>
                        <li>Pracownik odbiera przetłumaczone teksty.</li>
                        <li>Na podstawie zapamiętanych informacji odtwarza "chronione" spacje, dodając je z powrotem do tłumaczeń.</li>
                        <li>Wstawia przetłumaczony tekst z powrotem w jego oryginalne miejsce w strukturze HTML.</li>
                        <li>Gotowy wynik jest zapisywany do nowego pliku CSV z końcówką "_translated".</li>
                    </ul>
                </li>
            </ol>"""
        )
        start_layout.addWidget(self.start_button)
        start_layout.addWidget(info_label)
        start_layout.addStretch()
        main_layout.addLayout(start_layout)

        # Postęp i status
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Oczekiwanie na wybór pliku...")
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

        self.controls_to_toggle = [
            self.select_file_button, self.load_columns_button, self.start_button,
            self.source_lang_combo, self.target_lang_combo, self.num_workers_input,
            self.requests_per_sec_input
        ]



    def prepare_language_list(self):
        try:
            full_lang_list = GoogleTranslator().get_supported_languages(as_dict=True)
            self.language_map_code_to_name = {code: name.capitalize() for name, code in full_lang_list.items()}
            preferred_languages = {"Polski": "pl", "Angielski": "en", "Niemiecki": "de", "Francuski": "fr", "Hiszpański": "es", "Włoski": "it", "Czeski": "cs", "Słowacki": "sk", "Ukraiński": "uk", "Rosyjski": "ru"}
            self.language_map_display = preferred_languages.copy()
            for code, name in sorted(self.language_map_code_to_name.items(), key=lambda item: item[1]):
                if code not in preferred_languages.values(): self.language_map_display[name] = code
            
            self.source_lang_combo.addItems(self.language_map_display.keys())
            self.target_lang_combo.addItems(self.language_map_display.keys())
            self.source_lang_combo.setCurrentText("Polski")
            self.target_lang_combo.setCurrentText("Angielski")
        except Exception as e:
            self.language_map_display = {"Polski": "pl", "Angielski": "en", "Niemiecki": "de"}
            QMessageBox.warning(self, "Błąd sieci", f"Nie udało się pobrać pełnej listy języków: {e}\nUżywana jest lista podstawowa.")

    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz plik CSV", "", "CSV Files (*.csv);;All Files (*)")
        if path:
            self.input_csv_path = path
            self.selected_file_label.setText(os.path.basename(path))
            self.log_info(f"Wybrano plik: {path}")
            self.load_columns_button.setEnabled(True)

    def load_columns_from_csv(self):
        if not self.input_csv_path:
            QMessageBox.critical(self, "Błąd", "Najpierw wybierz plik!")
            return
        
        for i in reversed(range(self.column_checkbox_layout.count())): 
            self.column_checkbox_layout.itemAt(i).widget().setParent(None)
        self.column_vars = {}

        try:
            df_columns = pd.read_csv(self.input_csv_path, nrows=0, on_bad_lines='skip').columns.tolist()
            self.log_info(f"Znaleziono kolumny: {df_columns}")
            for col in df_columns:
                if col != ID_COLUMN:
                    cb = QCheckBox(col)
                    self.column_checkbox_layout.addWidget(cb)
                    self.column_vars[col] = cb
        except Exception as e:
            QMessageBox.critical(self, "Błąd", f"Nie można wczytać pliku: {e}")

    def start_translation(self):
        if not self.input_csv_path:
            QMessageBox.critical(self, "Błąd", "Wybierz plik!")
            return

        source_display = self.source_lang_combo.currentText()
        target_display = self.target_lang_combo.currentText()
        source = self.language_map_display[source_display]
        target = self.language_map_display[target_display]

        columns = [col for col, cb in self.column_vars.items() if cb.isChecked()]
        if not columns:
            QMessageBox.critical(self, "Błąd", "Wybierz kolumny do tłumaczenia!")
            return

        try:
            num_workers = int(self.num_workers_input.text())
            requests_per_sec = float(self.requests_per_sec_input.text())
            if num_workers <= 0 or requests_per_sec <= 0:
                raise ValueError("Wartości muszą być większe od zera.")
        except ValueError as e:
            QMessageBox.critical(self, "Błąd Wprowadzania", f"Niepoprawne wartości w ustawieniach zaawansowanych: {e}")
            return

        is_diagnostic_mode = self.diagnostic_checkbox.isChecked()

        self.toggle_controls(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Rozpoczynanie...")
        self.log_output.clear()
        self.total_chunks_processed = 0
        self.start_time = time.time()

        self.thread = QThread()
        self.worker = TranslationWorker(self, source, target, columns, num_workers, requests_per_sec, self.input_csv_path, is_diagnostic_mode)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        
        self.worker.progress.connect(self.update_progress)
        self.worker.log_info.connect(self.log_info)
        self.worker.log_error.connect(self.log_error)
        self.worker.update_status.connect(self.update_status_label)
        self.worker.finished.connect(self.task_finished)
        self.worker.cooldown_started.connect(self.handle_cooldown_start)
        self.worker.cooldown_finished.connect(self.handle_cooldown_finish)

        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def update_progress(self, count):
        self.total_chunks_processed += count
        p = self.total_chunks_processed
        m = self.total_chunks_to_process
        self.progress_bar.setValue(p)
        self.progress_bar.setMaximum(m)
        
        elapsed = time.time() - self.start_time
        frac = p / m if m > 0 else 0
        etr = (elapsed / frac - elapsed) if frac > 0.01 else 0
        
        if not self.is_cooldown:
            self.status_label.setText(f"Tłumaczenie: {p}/{m} | Pozostały czas: ~{self.format_time(etr)}")

    def task_finished(self, output_path, total_time):
        self.log_info(f"--- ZAKOŃCZONO ---")
        self.log_info(f"Wyniki zapisano w '{output_path}'.")
        self.status_label.setText(f"Zakończono! Czas: {self.format_time(total_time)}.")
        self.toggle_controls(True)
        self.thread.quit()

    def log_info(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")

    def log_error(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] BŁĄD: {message}")

    def update_status_label(self, text):
        self.status_label.setText(text)

    def handle_cooldown_start(self, duration):
        self.is_cooldown = True
        self.cooldown_remaining = duration
        self.update_cooldown_timer()

    def update_cooldown_timer(self):
        if self.cooldown_remaining < 0:
            self.is_cooldown = False
            self.status_label.setText("Testuję połączenie...")
            return
        
        minutes, seconds = divmod(self.cooldown_remaining, 60)
        self.status_label.setText(f"Zdalny ban. Kolejna próba za: {minutes:02d}:{seconds:02d}")
        self.cooldown_remaining -= 1
        threading.Timer(1, self.update_cooldown_timer).start()

    def handle_cooldown_finish(self):
        self.is_cooldown = False

    def toggle_controls(self, enabled):
        for control in self.controls_to_toggle:
            control.setEnabled(enabled)
        if enabled and self.input_csv_path:
            self.load_columns_button.setEnabled(True)
        elif not enabled:
            self.load_columns_button.setEnabled(False)

    def format_time(self, seconds):
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
