import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLineEdit, QLabel, QTextEdit, QDialog, QFormLayout, 
    QDialogButtonBox, QFileDialog, QFrame
)
from PyQt6.QtCore import QThread, pyqtSignal

# Importuj logikę z modułów
from logic.downloader import run_downloader
from logic.unpinner import run_unpinner
from logic.pinner import run_pinner
from logic.filter_csv import run_filter
from logic.description_downloader import run_description_downloader
from gui.translator_dialog import TranslatorDialog

# --- Wątek roboczy do operacji w tle ---
class Worker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            for message in self.func(*self.args, **self.kwargs):
                self.progress.emit(message)
        except Exception as e:
            self.progress.emit(f"Wystąpił krytyczny błąd w wątku: {e}")
        finally:
            self.finished.emit()

# --- Okna dialogowe do pobierania danych ---
class UnpinnerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Odepnij towary - Wprowadź dane")
        self.shop_id_input = QLineEdit(self)
        self.menu_id_input = QLineEdit(self)
        
        form_layout = QFormLayout()
        form_layout.addRow("Shop ID:", self.shop_id_input)
        form_layout.addRow("Menu ID:", self.menu_id_input)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def get_data(self):
        return self.shop_id_input.text(), self.menu_id_input.text()

class PinnerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Przypnij towary - Wprowadź dane")
        self.shop_id_input = QLineEdit(self)
        self.menu_id_input = QLineEdit(self)
        self.csv_path_input = QLineEdit(self)
        self.csv_browse_button = QPushButton("Przeglądaj...")
        self.csv_browse_button.clicked.connect(self.browse_csv)

        form_layout = QFormLayout()
        form_layout.addRow("Shop ID:", self.shop_id_input)
        form_layout.addRow("Menu ID:", self.menu_id_input)
        
        csv_layout = QHBoxLayout()
        csv_layout.addWidget(self.csv_path_input)
        csv_layout.addWidget(self.csv_browse_button)
        form_layout.addRow("Plik CSV:", csv_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def browse_csv(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Wybierz plik CSV", "", "CSV Files (*.csv)")
        if filename:
            self.csv_path_input.setText(filename)

    def get_data(self):
        return self.shop_id_input.text(), self.menu_id_input.text(), self.csv_path_input.text()

class FilterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filtruj CSV - Wprowadź dane")
        self.shop_id_input = QLineEdit(self)
        
        form_layout = QFormLayout()
        form_layout.addRow("Zostaw Shop ID:", self.shop_id_input)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def get_data(self):
        return self.shop_id_input.text()

# --- Główne okno aplikacji ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IdoKombajn")
        self.setGeometry(100, 100, 900, 700)
        self.initUI()

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        window_layout = QVBoxLayout(central_widget)

        config_layout = QFormLayout()
        self.base_url_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        config_layout.addRow("Base URL:", self.base_url_input)
        config_layout.addRow("API Key:", self.api_key_input)
        window_layout.addLayout(config_layout)

        columns_layout = QHBoxLayout()

        left_column_layout = QVBoxLayout()
        left_widget = QWidget()
        left_widget.setLayout(left_column_layout)

        left_column_layout.addWidget(QLabel("<b>CROSSBORDER - MENU</b>"))

        self.buttons = []
        btn_downloader = QPushButton("1. Pobierz informacje o elementach menu")
        btn_downloader.setToolTip("Pobiera pełną listę produktów...")
        btn_downloader.clicked.connect(self.run_downloader_task)
        self.buttons.append(btn_downloader)
        left_column_layout.addWidget(btn_downloader)

        btn_filter = QPushButton("2. Filtruj plik CSV")
        btn_filter.setToolTip("Filtruje plik 'produkty_menu_final.csv'...")
        btn_filter.clicked.connect(self.run_filter_task)
        self.buttons.append(btn_filter)
        left_column_layout.addWidget(btn_filter)

        btn_unpinner = QPushButton("3. Odepnij towary od Menu")
        btn_unpinner.setToolTip("Masowo usuwa powiązania produktów...")
        btn_unpinner.clicked.connect(self.run_unpinner_task)
        self.buttons.append(btn_unpinner)
        left_column_layout.addWidget(btn_unpinner)

        btn_pinner = QPushButton("4. Przypnij towary do Menu")
        btn_pinner.setToolTip("Masowo przypisuje produkty...")
        btn_pinner.clicked.connect(self.run_pinner_task)
        self.buttons.append(btn_pinner)
        left_column_layout.addWidget(btn_pinner)
        left_column_layout.addStretch()

        columns_layout.addWidget(left_widget)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        columns_layout.addWidget(line)

        right_column_layout = QVBoxLayout()
        right_widget = QWidget()
        right_widget.setLayout(right_column_layout)

        right_column_layout.addWidget(QLabel("<b>POZOSTAŁE</b>"))

        btn_desc_downloader = QPushButton("Pobierz nazwy i opisy produktów")
        btn_desc_downloader.setToolTip("Pobiera pełne dane o wszystkich produktach...")
        btn_desc_downloader.clicked.connect(self.run_description_downloader_task)
        self.buttons.append(btn_desc_downloader)
        right_column_layout.addWidget(btn_desc_downloader)

        btn_translator = QPushButton("Tłumacz Google")
        btn_translator.setToolTip("Otwiera zaawansowany translator plików CSV z obsługą HTML.")
        btn_translator.clicked.connect(self.run_translator_dialog)
        self.buttons.append(btn_translator)
        right_column_layout.addWidget(btn_translator)

        right_column_layout.addStretch()
        columns_layout.addWidget(right_widget)
        
        window_layout.addLayout(columns_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        window_layout.addWidget(QLabel("Logi:"))
        window_layout.addWidget(self.log_output)

        btn_clear_log = QPushButton("Wyczyść logi")
        btn_clear_log.clicked.connect(self.clear_log_output)
        window_layout.addWidget(btn_clear_log)

    def log(self, message):
        message = str(message)
        if "BŁĄD" in message or "krytyczny" in message.lower() or "error" in message.lower():
            color = "#FF5555"
        elif "ostrzeżenie" in message.lower() or "warning" in message.lower():
            color = "#F9A602"
        elif "--- rozpoczynam" in message.lower() or "pobieranie strony" in message.lower():
            color = "#50A8C8"
        elif "--- zadanie zakończone" in message.lower() or "ukończono" in message.lower() or "sukces" in message.lower():
            color = "#50C878"
        else:
            color = "#F0F0F0"
        
        self.log_output.append(f'<font color="{color}">{message.replace("\n", "<br>")}</font>')

    def clear_log_output(self):
        self.log_output.clear()

    def run_translator_dialog(self):
        dialog = TranslatorDialog(self)
        dialog.exec()

    def _start_task(self, func, *args, **kwargs):
        base_url = self.base_url_input.text()
        api_key = self.api_key_input.text()
        
        if func not in [run_filter]:
            if not base_url or not api_key:
                self.log("BŁĄD: Base URL i API Key nie mogą być puste!")
                return
        
        final_kwargs = {}
        if func not in [run_filter]:
            final_kwargs['base_url'] = base_url
            final_kwargs['api_key'] = api_key
        final_kwargs.update(kwargs)

        self.set_buttons_enabled(False)
        self.log(f"--- Rozpoczynam zadanie: {func.__name__} ---")
        self.worker = Worker(func, *args, **final_kwargs)
        self.worker.progress.connect(self.log)
        self.worker.finished.connect(self.task_finished)
        self.worker.start()

    def run_downloader_task(self):
        self._start_task(run_downloader)

    def run_description_downloader_task(self):
        self._start_task(run_description_downloader)

    def run_filter_task(self):
        dialog = FilterDialog(self)
        if dialog.exec():
            shop_id = dialog.get_data()
            if not shop_id.isdigit():
                self.log("BŁĄD: Shop ID musi być liczbą.")
                return
            self._start_task(run_filter, input_filename="produkty_menu_final.csv", output_filename="produkty_menu_final_filtered.csv", shop_id_to_keep=int(shop_id))

    def run_unpinner_task(self):
        dialog = UnpinnerDialog(self)
        if dialog.exec():
            shop_id, menu_id = dialog.get_data()
            if not (shop_id.isdigit() and menu_id.isdigit()):
                self.log("BŁĄD: Shop ID i Menu ID muszą być liczbami.")
                return
            self._start_task(run_unpinner, shop_id=int(shop_id), menu_id=int(menu_id))

    def run_pinner_task(self):
        dialog = PinnerDialog(self)
        if dialog.exec():
            shop_id, menu_id, csv_path = dialog.get_data()
            if not (shop_id.isdigit() and menu_id.isdigit()):
                self.log("BŁĄD: Shop ID i Menu ID muszą być liczbami.")
                return
            if not csv_path:
                self.log("BŁĄD: Musisz wybrać plik CSV.")
                return
            self._start_task(run_pinner, shop_id=int(shop_id), menu_id=int(menu_id), csv_filename=csv_path)

    def task_finished(self):
        self.log("--- Zadanie zakończone ---\n")
        self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled):
        for button in self.buttons:
            button.setEnabled(enabled)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    STYLESHEET = """
        QMainWindow, QDialog {
            background-color: #2B2B2B;
        }
        QLabel {
            color: #F0F0F0;
        }
        QPushButton {
            background-color: #3C3F41;
            color: #F0F0F0;
            border: 1px solid #555555;
            padding: 5px;
            min-height: 20px;
        }
        QPushButton:hover {
            background-color: #4A90E2;
            border: 1px solid #4A90E2;
        }
        QPushButton:pressed {
            background-color: #3F79C1;
        }
        QPushButton:disabled {
            background-color: #333333;
            color: #777777;
        }
        QLineEdit {
            background-color: #3C3F41;
            color: #F0F0F0;
            border: 1px solid #555555;
            padding: 5px;
        }
        QTextEdit {
            background-color: #252526;
            color: #F0F0F0;
            border: 1px solid #555555;
        }
        QToolTip {
            background-color: #3C3F41;
            color: #F0F0F0;
            border: 1px solid #555555;
        }
        QFrame[frameShape="5"], QFrame[frameShape="4"] { /* VLine, HLine */
            color: #555555;
        }
    """
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
