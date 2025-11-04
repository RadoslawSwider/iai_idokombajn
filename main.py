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
from gui.description_generator_dialog import DescriptionGeneratorDialog
from logic.update_descriptions import run_update_descriptions
from logic.copy_menu_nodes import run_copy_menu_nodes
from logic.update_priorities import run_update_priorities
from gui.new_modules_dialog import NewModulesDialog

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
        self.description_dialog = None
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

        # Helper function to create button with info icon
        def create_button_with_info(text, tooltip_text):
            layout = QHBoxLayout()
            button = QPushButton(text)
            self.buttons.append(button)
            
            info_label = QLabel("ⓘ")
            info_label.setToolTip(tooltip_text)
            
            layout.addWidget(button)
            layout.addWidget(info_label)
            layout.setStretch(0, 1) # Make button expand
            
            return button, layout

        # 1. Downloader
        downloader_tooltip = '''<h3>Moduł: Pobierz informacje o elementach menu</h3>
<p><b>Cel:</b> Pobranie z IdoSell pełnej listy wszystkich produktów i ich przypisań do menu w każdym ze sklepów.</p>
<b>Kroki:</b>
<ol>
    <li>Nawiązuje połączenie z API IdoSell przy użyciu Twojego Base URL i klucza API.</li>
    <li>Pobiera dane z endpointu <i>/product-menus</i>, strona po stronie, aby obsłużyć duże ilości danych.</li>
    <li>Zapisuje wszystkie znalezione przypisania do jednego pliku <b>produkty_menu_final.csv</b>.</li>
</ol>
<p><b>Wynik:</b> Plik CSV zawierający kluczowe informacje: <b>productId</b> (ID towaru), <b>shopId</b> (ID sklepu), <b>menuId</b> (ID menu) oraz <b>menuItemTextId</b> (węzły nawigacji). Ten plik jest podstawą dla modułów Filtruj, Odepnij i Przypnij.</p>'''
        btn_downloader, downloader_layout = create_button_with_info("Pobierz informacje o elementach menu", downloader_tooltip)
        btn_downloader.clicked.connect(self.run_downloader_task)
        left_column_layout.addLayout(downloader_layout)

        # 2. Filter
        filter_tooltip = '''<h3>Moduł: Filtruj plik CSV</h3>
<p><b>Cel:</b> Wyizolowanie z głównego pliku `produkty_menu_final.csv` danych dotyczących tylko jednego, konkretnego sklepu.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera okno dialogowe, w którym podajesz <b>Shop ID</b> sklepu, który chcesz zostawić.</li>
    <li>Wczytuje plik `produkty_menu_final.csv`.</li>
    <li>Filtruje wiersze, pozostawiając tylko te, gdzie wartość w kolumnie <i>shop_id</i> zgadza się z podanym przez Ciebie ID.</li>
    <li>Zapisuje wynik do nowego pliku <b>produkty_menu_final_filtered.csv</b>.</li>
</ol>
<p><b>Wynik:</b> Nowy, przefiltrowany plik CSV, gotowy do dalszej pracy, np. z modułem "Przypnij towary".</p>'''
        btn_filter, filter_layout = create_button_with_info("Filtruj plik CSV", filter_tooltip)
        btn_filter.clicked.connect(self.run_filter_task)
        left_column_layout.addLayout(filter_layout)

        # 3. Unpinner
        unpinner_tooltip = '''<h3>Moduł: Odepnij towary od Menu</h3>
<p><b>Cel:</b> Masowe usunięcie wszystkich produktów z wybranego menu w danym sklepie.</p>
<p><b>Uwaga:</b> Działa na podstawie pliku `produkty_menu_final.csv`, więc upewnij się, że jest on aktualny.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera okno dialogowe, w którym podajesz <b>Shop ID</b> oraz <b>Menu ID</b>.</li>
    <li>Na podstawie tych danych, moduł wyszukuje w pliku `produkty_menu_final.csv` wszystkie produkty przypisane do tego konkretnego menu.</li>
    <li>Dla każdego znalezionego produktu, wysyła do API IdoSell żądanie <b>DELETE</b>, które usuwa powiązanie produktu z menu.</li>
    <li>W logach na bieżąco raportuje, który produkt został pomyślnie odpięty lub przy którym wystąpił błąd.</li>
</ol>
<p><b>Wynik:</b> Produkty w IdoSell nie są już przypisane do podanego menu.</p>'''
        btn_unpinner, unpinner_layout = create_button_with_info("Odepnij towary od Menu", unpinner_tooltip)
        btn_unpinner.clicked.connect(self.run_unpinner_task)
        left_column_layout.addLayout(unpinner_layout)

        # 4. Pinner
        pinner_tooltip = '''<h3>Moduł: Przypnij towary do Menu</h3>
<p><b>Cel:</b> Masowe przypisanie listy produktów z pliku CSV do konkretnego menu w IdoSell.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera okno dialogowe, w którym podajesz <b>Shop ID</b>, <b>Menu ID</b> oraz wskazujesz <b>plik CSV</b> z listą produktów do przypięcia.</li>
    <li>Plik CSV musi zawierać kolumnę z identyfikatorami produktów (domyślnie `product_id`).</li>
    <li>Moduł wczytuje wskazany plik CSV.</li>
    <li>Dla każdego ID produktu z pliku, wysyła do API IdoSell żądanie <b>POST</b>, które tworzy powiązanie produktu z podanym menu w danym sklepie.</li>
    <li>W logach na bieżąco raportuje, który produkt został pomyślnie przypięty lub przy którym wystąpił błąd.</li>
</ol>
<p><b>Wynik:</b> Produkty z pliku CSV są przypisane do docelowego menu w IdoSell.</p>'''
        btn_pinner, pinner_layout = create_button_with_info("Przypnij towary do Menu", pinner_tooltip)
        btn_pinner.clicked.connect(self.run_pinner_task)
        left_column_layout.addLayout(pinner_layout)

        # Separator for new modules
        line_menu = QFrame()
        line_menu.setFrameShape(QFrame.Shape.HLine)
        line_menu.setFrameShadow(QFrame.Shadow.Sunken)
        left_column_layout.addWidget(line_menu)

        # 5. Copy Menu Nodes
        copy_nodes_tooltip = '''<h3>Moduł: Kopiuj strukturę menu (węzły)</h3>
<p><b>Cel:</b> Zreplikowanie całej struktury kategorii (węzłów) z jednego menu do drugiego, bez przypisywania produktów.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera okno, gdzie podajesz ID sklepu i menu (źródłowe i docelowe) oraz język.</li>
    <li>Pobiera strukturę menu ze źródła.</li>
    <li>Tworzy tę samą strukturę w menu docelowym, wysyłając dane w paczkach po 100 elementów, aby zminimalizować liczbę zapytań API.</li>
</ol>
<p><b>Wynik:</b> W docelowym menu powstaje taka sama hierarchia kategorii jak w menu źródłowym.</p>'''
        btn_copy_nodes, copy_nodes_layout = create_button_with_info("Kopiuj strukturę menu (węzły)", copy_nodes_tooltip)
        btn_copy_nodes.clicked.connect(self.run_copy_menu_nodes_task)
        left_column_layout.addLayout(copy_nodes_layout)

        # 6. Update Priorities
        update_priorities_tooltip = '''<h3>Moduł: Synchronizuj priorytety węzłów</h3>
<p><b>Cel:</b> Ustawienie w menu docelowym takiej samej kolejności (priorytetów) węzłów, jaka jest w menu źródłowym.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera okno, gdzie podajesz dane sklepów i menu (źródło i cel) oraz język aktualizacji.</li>
    <li>Porównuje elementy menu na podstawie ich <b>nazw</b> w języku polskim.</li>
    <li>Jeśli priorytet dla elementu o tej samej nazwie różni się, przygotowuje aktualizację dla docelowego języka.</li>
    <li>Wysyła zmiany do API w paczkach po 100.</li>
</ol>
<p><b>Wynik:</b> Węzły w menu docelowym mają tę samą kolejność co w źródłowym.</p>'''
        btn_update_priorities, update_priorities_layout = create_button_with_info("Synchronizuj priorytety węzłów", update_priorities_tooltip)
        btn_update_priorities.clicked.connect(self.run_update_priorities_task)
        left_column_layout.addLayout(update_priorities_layout)

        # 7. Update Descriptions
        update_descriptions_tooltip = '''<h3>Moduł: Synchronizuj opisy góra/dół</h3>
<p><b>Cel:</b> Przeniesienie opisów górnego i dolnego z węzłów menu źródłowego do docelowego.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera okno, gdzie podajesz dane sklepów i menu (źródło i cel) oraz język aktualizacji.</li>
    <li>Porównuje elementy menu na podstawie ich <b>nazw</b> w języku polskim.</li>
    <li>Jeśli opisy dla elementu o tej samej nazwie różnią się, przygotowuje aktualizację dla docelowego języka.</li>
    <li>Wysyła zmiany do API w paczkach po 100.</li>
</ol>
<p><b>Wynik:</b> Węzły w menu docelowym mają te same opisy co w źródłowym.</p>'''
        btn_update_descriptions, update_descriptions_layout = create_button_with_info("Synchronizuj opisy góra/dół", update_descriptions_tooltip)
        btn_update_descriptions.clicked.connect(self.run_update_descriptions_task)
        left_column_layout.addLayout(update_descriptions_layout)

        
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

        # 5. Description Downloader
        desc_downloader_tooltip = '''<h3>Moduł: Pobierz nazwy i opisy produktów</h3>
<p><b>Cel:</b> Pobranie z IdoSell nazw oraz długich opisów dla wszystkich produktów we wszystkich dostępnych językach.</p>
<b>Kroki:</b>
<ol>
    <li>Nawiązuje połączenie z API IdoSell.</li>
    <li>Pobiera dane z endpointu <i>/products</i>, strona po stronie. Prosi API o zwrócenie pól z tłumaczeniami (nazwy, opisy) dla wszystkich języków.</li>
    <li>Zapisuje wyniki do pliku <b>produkty.csv</b>.</li>
</ol>
<p><b>Wynik:</b> Plik CSV z kolumnami dla każdego języka, np. `product_id`, `name_pol`, `description_pol`, `name_eng`, `description_eng`, itd. Ten plik jest idealną bazą dla modułów "Tłumacz Google" oraz "Generator Opisów AI".</p>'''
        btn_desc_downloader, desc_downloader_layout = create_button_with_info("Pobierz nazwy i opisy produktów", desc_downloader_tooltip)
        btn_desc_downloader.clicked.connect(self.run_description_downloader_task)
        right_column_layout.addLayout(desc_downloader_layout)

        # 6. Translator
        translator_tooltip = '''<h3>Moduł: Tłumacz Google</h3>
<p><b>Cel:</b> Zaawansowane tłumaczenie danych w plikach CSV, z inteligentną obsługą kodu HTML.</p>
<b>Kroki:</b>
<ol>
    <li><b>Wybór i Ustawienia:</b> Otwierasz dedykowane okno, gdzie wybierasz plik CSV, języki, kolumny do tłumaczenia oraz parametry techniczne (liczba wątków, zapytania/sek).</li>
    <li><b>Inteligentna Ekstrakcja Tekstu:</b>
        <ul>
            <li>Skrypt analizuje każdą komórkę i <b>rozpoznaje kod HTML</b>.</li>
            <li>Wyciąga do tłumaczenia <u>tylko tekst widoczny dla użytkownika</u>, pozostawiając tagi HTML nienaruszone.</li>
            <li>Zawartość tagów &lt;style&gt; i &lt;script&gt; jest celowo pomijana, aby nie zniszczyć wyglądu.</li>
        </ul>
    </li>
    <li><b>Tłumaczenie Równoległe:</b>
        <ul>
            <li>Zebrane teksty są wysyłane do Google Translate w wielu wątkach jednocześnie, co znacznie przyspiesza pracę.</li>
            <li>Wbudowany "hamulec" chroni przed zablokowaniem przez Google. W razie bana, skrypt automatycznie czeka i wznawia pracę.</li>
        </ul>
    </li>
    <li><b>Składanie i Zapis:</b> Przetłumaczone fragmenty są wstawiane z powrotem w ich oryginalne miejsca w strukturze HTML. Wynik jest zapisywany do nowego pliku z końcówką <b>_translated.csv</b>.</li>
</ol>'''
        btn_translator, translator_layout = create_button_with_info("Tłumacz Google", translator_tooltip)
        btn_translator.clicked.connect(self.run_translator_dialog)
        right_column_layout.addLayout(translator_layout)

        # 7. AI Description Generator
        desc_generator_tooltip = '''<h3>Moduł: Generator Opisów AI</h3>
<p><b>Cel:</b> Tworzenie unikalnych, marketingowych opisów produktów przy użyciu sztucznej inteligencji (OpenAI).</p>
<b>Kroki:</b>
<ol>
    <li><b>Konfiguracja:</b> W dedykowanym oknie podajesz klucz API OpenAI, wybierasz plik CSV z produktami, definiujesz nazwy kolumn (ID i opis) oraz dostosowujesz prompt dla AI i opcje formatowania (ramka HTML).</li>
    <li><b>Etap 1: Ekstrakcja Cech (AI):</b> Skrypt czyści opis produktu z HTML i wysyła go do modelu <b>gpt-3.5-turbo</b> w celu wyodrębnienia kluczowych cech produktu.</li>
    <li><b>Etap 2: Tworzenie Treści (AI):</b> Wyodrębnione cechy są wstawiane do Twojego promptu i wysyłane do modelu <b>gpt-4o</b>, który generuje w formacie JSON nową nazwę, zajawkę, opis główny i listę zalet.</li>
    <li><b>Formatowanie i Zapis:</b>
        <ul>
            <li>Skrypt formatuje otrzymane dane jako estetyczny blok HTML (z wybranym kolorem) lub jako zwykły tekst.</li>
            <li>Wynik jest na bieżąco zapisywany do pliku z końcówką <b>_wygenerowane.csv</b>, co chroni postęp pracy.</li>
        </ul>
    </li>
</ol>
<p><b>Wynik:</b> Plik CSV z nowymi, gotowymi do użycia nazwami i opisami produktów.</p>'''
        btn_desc_generator, desc_generator_layout = create_button_with_info("Generator Opisów AI", desc_generator_tooltip)
        btn_desc_generator.clicked.connect(self.run_description_generator_dialog)
        right_column_layout.addLayout(desc_generator_layout)

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

    def run_description_generator_dialog(self):
        if not self.description_dialog:
            self.description_dialog = DescriptionGeneratorDialog(self)
        self.description_dialog.show()
        self.description_dialog.activateWindow()

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

    def run_copy_menu_nodes_task(self):
        dialog = NewModulesDialog("Kopiuj strukturę menu (węzły)", self)
        if dialog.exec():
            source_shop_id, source_menu_id, dest_shop_id, dest_menu_id, dest_lang_id = dialog.get_data()
            if not (source_shop_id.isdigit() and source_menu_id.isdigit() and dest_shop_id.isdigit() and dest_menu_id.isdigit()):
                self.log("BŁĄD: Wszystkie ID muszą być liczbami.")
                return
            if not dest_lang_id:
                self.log("BŁĄD: Musisz podać język.")
                return
            self._start_task(run_copy_menu_nodes, source_shop_id=int(source_shop_id), source_menu_id=int(source_menu_id), dest_shop_id=int(dest_shop_id), dest_menu_id=int(dest_menu_id), lang_id=dest_lang_id)

    def run_update_priorities_task(self):
        dialog = NewModulesDialog("Synchronizuj priorytety węzłów", self)
        if dialog.exec():
            source_shop_id, source_menu_id, dest_shop_id, dest_menu_id, dest_lang_id = dialog.get_data()
            if not (source_shop_id.isdigit() and source_menu_id.isdigit() and dest_shop_id.isdigit() and dest_menu_id.isdigit()):
                self.log("BŁĄD: Wszystkie ID muszą być liczbami.")
                return
            if not dest_lang_id:
                self.log("BŁĄD: Musisz podać język.")
                return
            self._start_task(run_update_priorities, source_shop_id=source_shop_id, source_menu_id=source_menu_id, dest_shop_id=dest_shop_id, dest_menu_id=dest_menu_id, dest_lang_id=dest_lang_id)

    def run_update_descriptions_task(self):
        dialog = NewModulesDialog("Synchronizuj opisy góra/dół", self)
        if dialog.exec():
            source_shop_id, source_menu_id, dest_shop_id, dest_menu_id, dest_lang_id = dialog.get_data()
            if not (source_shop_id.isdigit() and source_menu_id.isdigit() and dest_shop_id.isdigit() and dest_menu_id.isdigit()):
                self.log("BŁĄD: Wszystkie ID muszą być liczbami.")
                return
            if not dest_lang_id:
                self.log("BŁĄD: Musisz podać język.")
                return
            self._start_task(run_update_descriptions, source_shop_id=source_shop_id, source_menu_id=source_menu_id, dest_shop_id=dest_shop_id, dest_menu_id=dest_menu_id, dest_lang_id=dest_lang_id)


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
            padding: 4px;
            min-height: 18px;
            font-size: 11px;
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
