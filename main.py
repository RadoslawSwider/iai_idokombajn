import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLineEdit, QLabel, QTextEdit, QDialog, QFormLayout, 
    QDialogButtonBox, QFileDialog, QFrame, QSpinBox
)
from PyQt6.QtCore import QThread, pyqtSignal

# Importuj logikę z modułów
from logic.downloader import run_downloader
from logic.unpinner import run_unpinner
# run_pinner is no longer used directly
# from logic.pinner import run_pinner 
from logic.filter_csv import run_filter
from logic.description_downloader import run_description_downloader
from gui.translator_dialog import TranslatorDialog
from gui.description_generator_dialog import DescriptionGeneratorDialog
from gui.attribute_translator_dialog import AttributeTranslatorDialog
from gui.description_updater_dialog import DescriptionUpdaterDialog
from logic.update_descriptions import run_update_descriptions
from logic.copy_menu_nodes import run_copy_menu_nodes
from logic.update_priorities import run_update_priorities
from logic.sync_menu_filters import run_sync_menu_filters
from gui.new_modules_dialog import NewModulesDialog
from logic.id_based_downloader import run_id_based_downloader
# Import the new dialog
from gui.copy_assignments_dialog import CopyAssignmentsDialog

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
            import inspect
            if inspect.isgeneratorfunction(self.func) or inspect.isgenerator(self.func):
                for message in self.func(*self.args, **self.kwargs):
                    self.progress.emit(message)
            else:
                result = self.func(*self.args, **self.kwargs)
                if result:
                    self.progress.emit(str(result))
        except Exception as e:
            import traceback
            self.progress.emit(f"Wystąpił krytyczny błąd w wątku: {e}\n{traceback.format_exc()}")
        finally:
            self.finished.emit()

# --- Okna dialogowe (stare, niektóre mogą być już nieużywane) ---
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
        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)
    def get_data(self):
        return self.shop_id_input.text(), self.menu_id_input.text()

class IdBasedDownloaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pobierz dane po ID - Wybierz plik")
        self.csv_path_input = QLineEdit(self)
        self.csv_browse_button = QPushButton("Przeglądaj...")
        self.csv_browse_button.clicked.connect(self.browse_csv)
        layout = QVBoxLayout()
        csv_layout = QHBoxLayout()
        csv_layout.addWidget(QLabel("Plik CSV z ID:"))
        csv_layout.addWidget(self.csv_path_input)
        csv_layout.addWidget(self.csv_browse_button)
        layout.addLayout(csv_layout)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.setLayout(layout)
    def browse_csv(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Wybierz plik CSV z listą ID", "", "CSV Files (*.csv)")
        if filename:
            self.csv_path_input.setText(filename)
    def get_data(self):
        return self.csv_path_input.text()

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

        def create_button_with_info(text, tooltip_text):
            layout = QHBoxLayout()
            button = QPushButton(text)
            self.buttons.append(button)
            info_label = QLabel("ⓘ")
            info_label.setToolTip(tooltip_text)
            layout.addWidget(button)
            layout.addWidget(info_label)
            layout.setStretch(0, 1)
            return button, layout

        # 1. Downloader
        downloader_tooltip = '''<h3>Moduł: Pobierz informacje o elementach menu</h3>
<p><b>Cel:</b> Pobranie z IdoSell pełnej listy wszystkich produktów i ich przypisań do menu w każdym ze sklepów. Tworzy plik <b>produkty_menu_final.csv</b>, który jest niezbędny do działania modułu "Kopiuj przypisania".</p>'''
        btn_downloader, downloader_layout = create_button_with_info("Pobierz informacje o elementach menu", downloader_tooltip)
        btn_downloader.clicked.connect(self.run_downloader_task)
        left_column_layout.addLayout(downloader_layout)

        # 2. Filter
        filter_tooltip = '''<h3>Moduł: Filtruj plik CSV</h3>
<p><b>Cel:</b> Wyizolowanie z głównego pliku `produkty_menu_final.csv` danych dotyczących tylko jednego, konkretnego sklepu.</p>'''
        btn_filter, filter_layout = create_button_with_info("Filtruj plik CSV", filter_tooltip)
        btn_filter.clicked.connect(self.run_filter_task)
        left_column_layout.addLayout(filter_layout)

        # 3. Unpinner
        unpinner_tooltip = '''<h3>Moduł: Odepnij towary od Menu</h3>
<p><b>Cel:</b> Masowe usunięcie wszystkich produktów z wybranego menu w danym sklepie na podstawie pliku `produkty_menu_final.csv`.</p>'''
        btn_unpinner, unpinner_layout = create_button_with_info("Odepnij towary od Menu", unpinner_tooltip)
        btn_unpinner.clicked.connect(self.run_unpinner_task)
        left_column_layout.addLayout(unpinner_layout)

        # 4. Pinner (New logic)
        pinner_tooltip = '''<h3>Moduł: Kopiuj przypisania produktów</h3>
<p><b>Cel:</b> Masowe skopiowanie przypisań produktów z jednej kategorii menu do drugiej, nawet między różnymi sklepami i językami.</p>
<b>Kroki:</b>
<ol>
    <li>Otwiera zaawansowane okno, gdzie wybierasz sklep/menu/język <b>źródłowy</b> i <b>docelowy</b>.</li>
    <li>Pobiera i wyświetla strukturę menu źródłowego w formie drzewa.</li>
    <li>Wybierasz z drzewa kategorię, z której chcesz skopiować przypisania.</li>
    <li>Aplikacja na podstawie unikalnej ścieżki tekstowej kategorii (np. "Buty\\Sportowe") znajduje jej odpowiednik w menu docelowym.</li>
    <li>Zbiera listę wszystkich produktów przypisanych do kategorii źródłowej.</li>
    <li>Uruchamia proces masowego przypisywania zebranych produktów do znalezionej kategorii docelowej, używając szybkiej metody po ID.</li>
</ol>
<p><b>Wymagania:</b> Działanie modułu opiera się na aktualnym pliku <b>produkty_menu_final.csv</b>.</p>'''
        btn_pinner, pinner_layout = create_button_with_info("Kopiuj przypisania produktów", pinner_tooltip)
        btn_pinner.clicked.connect(self.run_copy_assignments_dialog) # New action
        left_column_layout.addLayout(pinner_layout)

        line_menu = QFrame()
        line_menu.setFrameShape(QFrame.Shape.HLine)
        line_menu.setFrameShadow(QFrame.Shadow.Sunken)
        left_column_layout.addWidget(line_menu)

        # Other buttons...
        copy_nodes_tooltip = '''<h3>Moduł: Kopiuj strukturę menu (węzły)</h3>
<p><b>Cel:</b> Sklonowanie całej struktury kategorii (węzłów) z jednego menu do drugiego, nawet między różnymi sklepami.</p>
<p><b>Działanie:</b></p>
<ol>
    <li>Moduł pobiera kompletną strukturę drzewa kategorii z wybranego <b>menu źródłowego</b>.</li>
    <li>Następnie odtwarza tę samą strukturę w <b>menu docelowym</b>, zachowując hierarchię (zagnieżdżenie) oraz kolejność (priorytety) poszczególnych kategorii.</li>
    <li>Proces odbywa się z wykorzystaniem paczek (batching), co znacznie przyspiesza operację przy dużej liczbie kategorii.</li>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Moduł kopiuje <b>tylko kategorie (węzły)</b>, bez przypisanych do nich produktów.</li>
    <li>Do skopiowania przypisań produktów służy moduł "Kopiuj przypisania produktów".</li>
    <li>Przed uruchomieniem upewnij się, że menu docelowe jest puste, aby uniknąć duplikacji lub nieoczekiwanych efektów.</li>
</ul>'''
        btn_copy_nodes, copy_nodes_layout = create_button_with_info("Kopiuj strukturę menu (węzły)", copy_nodes_tooltip)
        btn_copy_nodes.clicked.connect(self.run_copy_menu_nodes_task)
        left_column_layout.addLayout(copy_nodes_layout)

        update_priorities_tooltip = '''<h3>Moduł: Synchronizuj priorytety węzłów</h3>
<p><b>Cel:</b> Ujednolicenie kolejności (priorytetów) kategorii w menu docelowym, tak aby odpowiadała ona kolejności w menu źródłowym.</p>
<p><b>Działanie:</b></p>
<ol>
    <li>Moduł porównuje dwa menu (źródłowe i docelowe) na podstawie <b>unikalnej tekstowej ścieżki</b> każdej kategorii (np. "Buty/Sportowe/Do biegania"). Dzięki temu jest w stanie znaleźć odpowiadające sobie kategorie, nawet jeśli ich wewnętrzne ID są różne.</li>
    <li>Dla każdej pasującej pary kategorii, moduł sprawdza, czy ich priorytet (który decyduje o kolejności wyświetlania) jest taki sam.</li>
    <li>Jeśli priorytety się różnią, moduł przygotowuje i wysyła do IdoSell żądanie aktualizacji, nadając kategorii w menu docelowym priorytet z jej odpowiednika w menu źródłowym.</li>
    <li>Wszystkie zmiany są wysyłane w zoptymalizowanych paczkach, co zapewnia wysoką wydajność.</li>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Moduł do poprawnego mapowania kategorii używa polskiej wersji językowej obu menu jako bazy.</li>
    <li>Synchronizacja dotyczy tylko kolejności. Nazwy i inne atrybuty kategorii nie są zmieniane.</li>
</ul>'''
        btn_update_priorities, update_priorities_layout = create_button_with_info("Synchronizuj priorytety węzłów", update_priorities_tooltip)
        btn_update_priorities.clicked.connect(self.run_update_priorities_task)
        left_column_layout.addLayout(update_priorities_layout)

        sync_filters_tooltip = '''<h3>Moduł: Synchronizuj filtry menu</h3>
<p><b>Cel:</b> Porównuje dwa menu (źródłowe i docelowe) i kopiuje ustawienia filtrów dla pasujących węzłów.</p>
<p>Proces mapuje węzły na podstawie ich pełnej ścieżki (np. "Kategoria/Podkategoria"), a następnie dla każdej znalezionej pary synchronizuje aktywne filtry, dopasowując je po nazwie.</p>'''
        btn_sync_filters, sync_filters_layout = create_button_with_info("Synchronizuj filtry menu", sync_filters_tooltip)
        btn_sync_filters.clicked.connect(self.run_sync_filters_task)
        left_column_layout.addLayout(sync_filters_layout)

        update_descriptions_tooltip = '''<h3>Moduł: Synchronizuj opisy góra/dół</h3>
<p><b>Cel:</b> Skopiowanie opisów górnych i dolnych z polskiej wersji menu źródłowego do wybranej wersji językowej menu docelowego.</p>
<p><b>Działanie:</b></p>
<ol>
    <li>Moduł pobiera wszystkie kategorie z <b>menu źródłowego</b> (w języku polskim) i tworzy mapę ich nazw oraz przypisanych do nich opisów (górnego i dolnego).</li>
    <li>Następnie pobiera kategorie z <b>menu docelowego</b> (również po polsku), aby znaleźć ich odpowiedniki na podstawie <b>identycznej nazwy</b>.</li>
    <li>Dla każdej znalezionej pary, moduł porównuje opisy. Jeśli się różnią, przygotowuje aktualizację.</li>
    <li>Aktualizacja jest wysyłana do menu docelowego dla wybranego <b>docelowego języka</b>. W praktyce oznacza to, że np. niemieckie opisy w menu docelowym zostaną nadpisane polskimi opisami z menu źródłowego.</li>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Moduł jest przydatny do ujednolicania lub "resetowania" opisów w menu obcojęzycznym, aby miały tę samą treść co w menu polskim (np. przed procesem tłumaczenia).</li>
    <li>Kategorie w obu menu muszą mieć <b>identyczne nazwy w języku polskim</b>, aby zostały poprawnie dopasowane.</li>
</ul>'''
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
        
        # ... (Right column buttons are the same, omitted for brevity)
        desc_downloader_tooltip = '''<h3>Moduł: Pobierz nazwy i opisy produktów</h3>
<p><b>Cel:</b> Pobranie wszystkich aktywnych produktów ze sklepu i zapisanie ich danych tekstowych (nazwa, opis krótki, opis długi) do pliku CSV.</p>
<p><b>Działanie:</b></p>
<ol>
    <li>Moduł łączy się z API IdoSell i pobiera listę wszystkich <b>aktywnych</b> produktów w sklepie.</li>
    <li>Proces odbywa się za pomocą paginacji (pobieranie produktów w paczkach po 100), co pozwala obsłużyć nawet bardzo duże bazy produktowe.</li>
    <li>Moduł jest odporny na chwilowe problemy z siecią - w razie błędu ponawia próbę połączenia 10 razy co 60 sekund.</li>
    <li>Po pobraniu wszystkich danych, tworzy plik <b>produkty.csv</b>.</li>
    <li>W pliku tym, dla każdego produktu, znajdują się jego ID oraz kolumny z nazwą, opisem krótkim i opisem długim dla <b>każdego języka</b> skonfigurowanego w panelu IdoSell.</li>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Plik <b>produkty.csv</b> jest kluczowy dla działania modułów "Tłumacz Google" oraz "Aktualizuj Nazwy i Opisy". Należy go wygenerować przed ich użyciem.</li>
    <li>Pobieranie może zająć dłuższą chwilę przy dużej liczbie produktów.</li>
</ul>'''
        btn_desc_downloader, desc_downloader_layout = create_button_with_info("Pobierz nazwy i opisy produktów", desc_downloader_tooltip)
        btn_desc_downloader.clicked.connect(self.run_description_downloader_task)
        right_column_layout.addLayout(desc_downloader_layout)
        id_based_downloader_tooltip = '''<h3>Moduł: Pobierz nazwy i opisy produktów (na bazie ID)</h3>
<p><b>Cel:</b> Szybkie pobranie nazw i opisów (w języku polskim) tylko dla określonej listy produktów, których ID znajdują się w podanym pliku CSV.</p>
<p><b>Działanie:</b></p>
<ol>
    <li>Moduł prosi o wskazanie pliku CSV zawierającego kolumnę z identyfikatorami produktów (np. o nazwie '@id', 'product_id' lub 'ID').</li>
    <li>Aby zminimalizować liczbę zapytań do API, moduł w tle pobiera dane <b>wszystkich aktywnych produktów</b> ze sklepu, wykorzystując do tego wiele wątków w celu przyspieszenia procesu.</li>
    <li>Po pobraniu pełnej listy, filtruje ją, zostawiając tylko te produkty, których ID znajdowały się w pliku wejściowym.</li>
    <li>Dla znalezionych produktów, moduł tworzy dwa pliki wynikowe:</li>
    <ul>
        <li><b>[nazwa_pliku]_products.csv</b>: Plik CSV z ID, nazwą, opisem krótkim i długim (w języku polskim).</li>
        <li><b>[nazwa_pliku]_missing.txt</b>: Plik tekstowy z listą ID, których nie udało się znaleźć w sklepie (np. były nieaktywne lub usunięte).</li>
    </ul>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Jest to znacznie wydajniejsza metoda niż odpytywanie API o każdy produkt z osobna, zwłaszcza przy dużych listach ID.</li>
    <li>Moduł zawsze pobiera opisy w języku polskim, niezależnie od innych ustawień.</li>
</ul>'''
        btn_id_based_downloader, id_based_downloader_layout = create_button_with_info("Pobierz nazwy i opisy produktów (na bazie ID)", id_based_downloader_tooltip)
        btn_id_based_downloader.clicked.connect(self.run_id_based_downloader_task)
        right_column_layout.addLayout(id_based_downloader_layout)
        translator_tooltip = '''<h3>Moduł: Tłumacz Google</h3>
<p><b>Cel:</b> Masowe tłumaczenie danych produktowych z pliku CSV, z inteligentną obsługą HTML i zaawansowaną ochroną przed blokadą API.</p>
<p><b>Działanie:</b></p>
<p>Po otwarciu okna modułu, możesz:</p>
<ol>
    <li>Wybrać plik CSV (np. wygenerowany przez moduł "Pobierz nazwy i opisy").</li>
    <li>Wybrać język źródłowy, docelowy oraz kolumny do tłumaczenia.</li>
    <li>Dostosować ustawienia wydajności (liczba wątków, szybkość zapytań).</li>
    <li>Uruchomić proces, który:
        <ul>
            <li>Inteligentnie parsuje HTML, tłumacząc tylko tekst widoczny dla użytkownika i pozostawiając nienaruszony kod.</li>
            <li>Dzieli pracę na wiele wątków, aby zmaksymalizować prędkość.</li>
            <li>Automatycznie zarządza limitami zapytań Google i wstrzymuje pracę w razie blokady, aby uniknąć trwałego bana.</li>
            <li>Zapisuje wynik do nowego pliku `..._translated.csv` oraz tworzy raport błędów.</li>
        </ul>
    </li>
</ol>
<p>Moduł posiada również tryb poprawiania błędów z poprzednich uruchomień.</p>'''
        btn_translator, translator_layout = create_button_with_info("Tłumacz Google", translator_tooltip)
        btn_translator.clicked.connect(self.run_translator_dialog)
        right_column_layout.addLayout(translator_layout)
        desc_updater_tooltip = '''<h3>Moduł: Aktualizuj Nazwy i Opisy</h3>
<p><b>Cel:</b> Masowa aktualizacja nazw oraz opisów (krótkiego i długiego) dla produktów w panelu IdoSell, na podstawie danych z pliku CSV.</p>
<p><b>Działanie:</b></p>
<p>Moduł otwiera nowe okno, w którym:</p>
<ol>
    <li>Wybierasz plik CSV zawierający zaktualizowane dane (np. plik `..._translated.csv` z modułu Tłumacza).</li>
    <li>Określasz ID sklepu (`shopId`) oraz ID języka (`langId`), dla którego chcesz wprowadzić zmiany.</li>
    <li><b>Mapujesz kolumny:</b> Wskazujesz, która kolumna w Twoim pliku odpowiada za ID produktu, która za nową nazwę, a które za nowe opisy. Daje to dużą elastyczność i nie narzuca sztywnej struktury pliku.</li>
    <li>Po uruchomieniu, moduł wysyła dane do IdoSell w zoptymalizowanych paczkach, aktualizując produkty w wybranym języku.</li>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Jest to idealne narzędzie do wgrywania tłumaczeń przygotowanych wcześniej w module "Tłumacz Google".</li>
    <li>Przed użyciem upewnij się, że Twój plik CSV zawiera kolumnę z poprawnymi identyfikatorami produktów.</li>
</ul>'''
        btn_desc_updater, desc_updater_layout = create_button_with_info("Aktualizuj Nazwy i Opisy", desc_updater_tooltip)
        btn_desc_updater.clicked.connect(self.open_description_updater_dialog)
        right_column_layout.addLayout(desc_updater_layout)
        desc_generator_tooltip = '''<h3>Moduł: Generator Opisów AI</h3>
<p><b>Cel:</b> Automatyczne tworzenie profesjonalnych, marketingowych opisów produktów przy użyciu sztucznej inteligencji (OpenAI GPT).</p>
<p><b>Działanie:</b></p>
<p>Moduł otwiera okno, w którym konfigurujesz dwuetapowy proces AI:</p>
<ol>
    <li><b>Wybór danych:</b> Wskazujesz plik CSV z produktami i kolumnę zawierającą obecny, np. techniczny opis.</li>
    <li><b>Konfiguracja AI:</b> Wprowadzasz swój klucz API OpenAI oraz własny, szczegółowy prompt, który definiuje styl i format wynikowy (np. "stwórz chwytliwą nazwę, zajawkę i 3 cechy marketingowe w formie JSON").</li>
    <li><b>Proces AI - Krok 1 (Analiza):</b> Dla każdego produktu, model <b>GPT-3.5-Turbo</b> najpierw analizuje istniejący opis i wyodrębnia z niego kluczowe cechy (np. materiał, wymiary).</li>
    <li><b>Proces AI - Krok 2 (Kreacja):</b> Wyodrębnione cechy są wstawiane do Twojego promptu i wysyłane do modelu <b>GPT-4o</b>, który generuje nową, kreatywną treść zgodnie z Twoimi wytycznymi.</li>
    <li><b>Wynik:</b> Wygenerowane opisy są opcjonalnie formatowane w estetyczną ramkę HTML i zapisywane w nowym pliku `..._wygenerowane.csv`. Proces można wznowić, jeśli zostanie przerwany.</li>
</ol>'''
        btn_desc_generator, desc_generator_layout = create_button_with_info("Generator Opisów AI", desc_generator_tooltip)
        btn_desc_generator.clicked.connect(self.run_description_generator_dialog)
        right_column_layout.addLayout(desc_generator_layout)
        attr_translator_tooltip = """<h3>Moduł: Tłumacz Atrybutów ALT/TITLE</h3>
<p><b>Cel:</b> Precyzyjne tłumaczenie wyłącznie atrybutów <code>alt</code> (tekst alternatywny dla obrazków) oraz <code>title</code> (podpowiedź po najechaniu) w kodzie HTML opisów produktów.</p>
<p><b>Działanie:</b></p>
<p>Moduł ten jest wyspecjalizowanym narzędziem, które:</p>
<ol>
    <li>Przeszukuje kod HTML w wybranej kolumnie pliku CSV w poszukiwaniu tagów z atrybutami <code>alt="..."</code> i <code>title="..."</code>.</li>
    <li>Zbiera wszystkie unikalne teksty z tych atrybutów, aby uniknąć wielokrotnego tłumaczenia tej samej frazy.</li>
    <li>Tłumaczy zebrane teksty z języka polskiego na wybrany język docelowy, używając wydajnych zapytań wsadowych (batch).</li>
    <li>Na koniec, wstawia przetłumaczone frazy z powrotem do odpowiednich atrybutów <code>alt</code> i <code>title</code>, pozostawiając resztę kodu HTML i widocznego opisu nietkniętą.</li>
    <li>Wynik jest zapisywany w nowej kolumnie w pliku `..._generated.csv`.</li>
</ol>
<p><b>Ważne:</b></p>
<ul>
    <li>Moduł jest kluczowy dla SEO i dostępności (accessibility) na rynkach zagranicznych.</li>
    <li>Tłumaczy <b>tylko</b> zawartość atrybutów, a nie główny tekst opisu.</li>
</ul>"""
        btn_attr_translator, attr_translator_layout = create_button_with_info("Tłumacz Atrybutów ALT/TITLE", attr_translator_tooltip)
        btn_attr_translator.clicked.connect(self.run_attribute_translator_dialog)
        right_column_layout.addLayout(attr_translator_layout)

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
        if "BŁĄD" in message or "krytyczny" in message.lower() or "error" in message.lower(): color = "#FF5555"
        elif "ostrzeżenie" in message.lower() or "warning" in message.lower(): color = "#F9A602"
        elif "--- rozpoczynam" in message.lower() or "pobieranie strony" in message.lower(): color = "#50A8C8"
        elif "--- zadanie zakończone" in message.lower() or "ukończono" in message.lower() or "sukces" in message.lower(): color = "#50C878"
        else: color = "#F0F0F0"
        self.log_output.append(f'<font color="{color}">{message.replace("\n", "<br>")}</font>')

    def clear_log_output(self):
        self.log_output.clear()

    # --- New method to run the copy assignments dialog ---
    def run_copy_assignments_dialog(self):
        base_url = self.base_url_input.text().strip()
        api_key = self.api_key_input.text().strip()
        if not base_url or not api_key:
            self.log("BŁĄD: Base URL i Klucz API nie mogą być puste!")
            return
        
        dialog = CopyAssignmentsDialog(base_url, api_key, self)
        # The dialog's start_pinner_task signal is connected to _start_task
        # The dialog will emit the function to run (run_pinner_by_id) and its args
        dialog.start_background_task.connect(self._start_task)
        dialog.exec()

    def run_translator_dialog(self):
        dialog = TranslatorDialog(self)
        dialog.exec()

    def open_description_updater_dialog(self):
        api_key = self.api_key_input.text().strip()
        base_url = self.base_url_input.text().strip()
        if not api_key or not base_url:
            self.log("BŁĄD: Base URL i Klucz API w głównym oknie nie mogą być puste!")
            return
        dialog = DescriptionUpdaterDialog(api_key=api_key, base_url=base_url, parent=self)
        dialog.exec()

    def run_description_generator_dialog(self):
        if not self.description_dialog:
            self.description_dialog = DescriptionGeneratorDialog(self)
        self.description_dialog.show()
        self.description_dialog.activateWindow()

    def run_attribute_translator_dialog(self):
        dialog = AttributeTranslatorDialog(self)
        dialog.exec()

    def _start_task(self, func, args, kwargs):
        base_url = self.base_url_input.text()
        api_key = self.api_key_input.text()
        
        local_functions = [run_filter] 
        
        # For tasks started from dialogs, the API keys might already be in kwargs
        final_kwargs = kwargs.copy()

        if func not in local_functions:
            if 'base_url' not in final_kwargs:
                final_kwargs['base_url'] = base_url
            if 'api_key' not in final_kwargs:
                final_kwargs['api_key'] = api_key

        if not final_kwargs.get('base_url') or not final_kwargs.get('api_key'):
             if func not in local_functions:
                self.log("BŁĄD: Base URL i API Key nie mogą być puste!")
                return
        
        if 'progress_callback' not in final_kwargs:
            final_kwargs['progress_callback'] = self.log

        self.set_buttons_enabled(False)
        self.log(f"--- Rozpoczynam zadanie: {func.__name__} ---")
        
        self.worker = Worker(func, *args, **final_kwargs)
        self.worker.progress.connect(self.log)
        self.worker.finished.connect(self.task_finished)
        self.worker.start()

    def run_downloader_task(self):
        self._start_task(run_downloader, [], {{}})

    def run_description_downloader_task(self):
        self._start_task(run_description_downloader, [], {{}})

    def run_id_based_downloader_task(self):
        dialog = IdBasedDownloaderDialog(self)
        if dialog.exec():
            csv_path = dialog.get_data()
            if not csv_path:
                self.log("BŁĄD: Nie wybrano pliku CSV.")
                return
            self._start_task(run_id_based_downloader, [], {'input_csv_path': csv_path})

    def run_filter_task(self):
        dialog = FilterDialog(self)
        if dialog.exec():
            shop_id = dialog.get_data()
            if not shop_id.isdigit():
                self.log("BŁĄD: Shop ID musi być liczbą.")
                return
            self._start_task(run_filter, [], {'input_filename': "produkty_menu_final.csv", 'output_filename': "produkty_menu_final_filtered.csv", 'shop_id_to_keep': int(shop_id)})

    def run_unpinner_task(self):
        dialog = UnpinnerDialog(self)
        if dialog.exec():
            shop_id, menu_id = dialog.get_data()
            if not (shop_id.isdigit() and menu_id.isdigit()):
                self.log("BŁĄD: Shop ID i Menu ID muszą być liczbami.")
                return
            self._start_task(run_unpinner, [], {'shop_id': int(shop_id), 'menu_id': int(menu_id)})

    # The old run_pinner_task is now removed.

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
            self._start_task(run_copy_menu_nodes, [], {'source_shop_id': int(source_shop_id), 'source_menu_id': int(source_menu_id), 'dest_shop_id': int(dest_shop_id), 'dest_menu_id': int(dest_menu_id), 'lang_id': dest_lang_id})

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
            self._start_task(run_update_priorities, [], {'source_shop_id': source_shop_id, 'source_menu_id': source_menu_id, 'dest_shop_id': dest_shop_id, 'dest_menu_id': dest_menu_id, 'dest_lang_id': dest_lang_id})

    def run_sync_filters_task(self):
        dialog = NewModulesDialog("Synchronizuj filtry menu", self)
        if dialog.exec():
            source_shop_id, source_menu_id, dest_shop_id, dest_menu_id, source_lang_id, dest_lang_id = dialog.get_data()
            if not (source_shop_id.isdigit() and source_menu_id.isdigit() and dest_shop_id.isdigit() and dest_menu_id.isdigit()):
                self.log("BŁĄD: Wszystkie ID muszą być liczbami.")
                return
            if not source_lang_id:
                self.log("BŁĄD: Musisz podać język źródłowy.")
                return
            self._start_task(run_sync_menu_filters, [], {
                'source_shop_id': int(source_shop_id), 
                'source_menu_id': int(source_menu_id), 
                'dest_shop_id': int(dest_shop_id), 
                'dest_menu_id': int(dest_menu_id), 
                'lang_id': source_lang_id,
                'dest_lang_id': dest_lang_id
            })

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
            self._start_task(run_update_descriptions, [], {'source_shop_id': source_shop_id, 'source_menu_id': source_menu_id, 'dest_shop_id': dest_shop_id, 'dest_menu_id': dest_menu_id, 'dest_lang_id': dest_lang_id})

    def task_finished(self):
        self.log("--- Zadanie zakończone ---\n")
        self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled):
        for button in self.buttons:
            button.setEnabled(enabled)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    STYLESHEET = """
        QMainWindow, QDialog { background-color: #2B2B2B; }
        QLabel { color: #F0F0F0; }
        QPushButton { background-color: #3C3F41; color: #F0F0F0; border: 1px solid #555555; padding: 4px; min-height: 18px; font-size: 11px; }
        QPushButton:hover { background-color: #4A90E2; border: 1px solid #4A90E2; }
        QPushButton:pressed { background-color: #3F79C1; }
        QPushButton:disabled { background-color: #333333; color: #777777; }
        QLineEdit { background-color: #3C3F41; color: #F0F0F0; border: 1px solid #555555; padding: 5px; }
        QTextEdit { background-color: #252526; color: #F0F0F0; border: 1px solid #555555; }
        QToolTip { background-color: #3C3F41; color: #F0F0F0; border: 1px solid #555555; }
        QFrame[frameShape="5"], QFrame[frameShape="4"] { color: #555555; }
    """
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
