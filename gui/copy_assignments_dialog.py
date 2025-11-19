# gui/copy_assignments_dialog.py

import csv
from collections import defaultdict
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QFormLayout, QMessageBox, 
    QProgressDialog, QCheckBox
)
from PyQt6.QtCore import pyqtSignal, QThread, Qt

# Import the new orchestrator function
from logic.copy_assignments import run_copy_all_assignments, get_menu_data
from logic.pinner import run_pinner_by_id

class TaskThread(QThread):
    """A generic worker thread for running different tasks."""
    finished = pyqtSignal(object, str)

    def __init__(self, task_function, *args, **kwargs):
        super().__init__()
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.task_function(*self.args, **self.kwargs)
            self.finished.emit(result, None)
        except Exception as e:
            import traceback
            self.finished.emit(None, f"{e}\n{traceback.format_exc()}")

class CopyAssignmentsDialog(QDialog):
    start_background_task = pyqtSignal(object, list, dict)

    def __init__(self, base_url, api_key, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.setWindowTitle("Kopiuj przypisania produktów (Pinner v2)")
        self.setMinimumSize(800, 700)
        self.worker_thread = None
        self.progress_dialog = None
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        selection_layout = QHBoxLayout()

        source_group = QGroupBox("1. Źródło (skąd kopiować)")
        source_layout = QFormLayout()
        self.source_shop_combo = QComboBox()
        self.source_menu_combo = QComboBox()
        self.source_lang_combo = QComboBox()
        self.fetch_source_button = QPushButton("Pobierz strukturę menu")
        source_layout.addRow("Sklep źródłowy:", self.source_shop_combo)
        source_layout.addRow("Menu źródłowe:", self.source_menu_combo)
        source_layout.addRow("Język menu:", self.source_lang_combo)
        source_layout.addRow(self.fetch_source_button)
        source_group.setLayout(source_layout)

        target_group = QGroupBox("2. Cel (gdzie przypisać)")
        target_layout = QFormLayout()
        self.target_shop_combo = QComboBox()
        self.target_menu_combo = QComboBox()
        self.target_lang_combo = QComboBox()
        target_layout.addRow("Sklep docelowy:", self.target_shop_combo)
        target_layout.addRow("Menu docelowe:", self.target_menu_combo)
        target_layout.addRow("Język docelowy:", self.target_lang_combo)
        target_group.setLayout(target_layout)

        selection_layout.addWidget(source_group)
        selection_layout.addWidget(target_group)
        main_layout.addLayout(selection_layout)

        # --- Checkbox for "Copy All" ---
        self.copy_all_checkbox = QCheckBox("Kopiuj przypisania dla całego menu (wszystkich kategorii)")
        main_layout.addWidget(self.copy_all_checkbox)

        tree_group = QGroupBox("3. Wybierz kategorię źródłową z drzewa (jeśli nie kopiujesz całości)")
        tree_layout = QVBoxLayout()
        self.menu_tree = QTreeWidget()
        self.menu_tree.setHeaderLabels(["Nazwa kategorii", "Ścieżka (item_textid)", "ID węzła"])
        self.menu_tree.setColumnWidth(0, 350)
        self.menu_tree.setColumnWidth(1, 300)
        tree_layout.addWidget(self.menu_tree)
        tree_group.setLayout(tree_layout)
        main_layout.addWidget(tree_group)

        self.run_button = QPushButton("4. Uruchom proces")
        self.run_button.setEnabled(False)
        main_layout.addWidget(self.run_button)

        self.populate_combos()

        # --- Connections ---
        self.fetch_source_button.clicked.connect(self.fetch_and_display_menu)
        self.menu_tree.currentItemChanged.connect(self.on_selection_changed)
        self.copy_all_checkbox.stateChanged.connect(self.on_selection_changed)
        self.run_button.clicked.connect(self.run_process)

    def populate_combos(self):
        dummy_shops = {"1": "bajamoto.pl", "2": "sklep-czeski", "5": "sklep-niemiecki"}
        dummy_menus = {"1": "Menu główne", "3": "Menu motocykle"}
        dummy_langs = {"pol": "Polski", "cze": "Czeski", "eng": "Angielski", "ger": "Niemiecki"}
        for combo in [self.source_shop_combo, self.target_shop_combo]:
            for shop_id, shop_name in dummy_shops.items():
                combo.addItem(f"{shop_name} (ID: {shop_id})", shop_id)
        for combo in [self.source_menu_combo, self.target_menu_combo]:
            for menu_id, menu_name in dummy_menus.items():
                combo.addItem(f"{menu_name} (ID: {menu_id})", menu_id)
        for combo in [self.source_lang_combo, self.target_lang_combo]:
            for lang_id, lang_name in dummy_langs.items():
                combo.addItem(f"{lang_name} ({lang_id})", lang_id)

    def on_selection_changed(self):
        is_copy_all = self.copy_all_checkbox.isChecked()
        self.menu_tree.setEnabled(not is_copy_all)
        
        # Enable run button if "copy all" is checked, or if a tree item is selected
        can_run = is_copy_all or (self.menu_tree.currentItem() is not None)
        self.run_button.setEnabled(can_run)

    def _show_progress(self, title, label):
        self.progress_dialog = QProgressDialog(label, "Anuluj", 0, 0, self)
        self.progress_dialog.setWindowTitle(title)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()

    def fetch_and_display_menu(self):
        self.fetch_source_button.setEnabled(False)
        self.fetch_source_button.setText("Pobieranie...")
        self.menu_tree.clear()
        self.on_selection_changed()

        shop_id = self.source_shop_combo.currentData()
        menu_id = self.source_menu_combo.currentData()
        lang_id = self.source_lang_combo.currentData()

        self.worker_thread = TaskThread(get_menu_data, self.base_url, self.api_key, shop_id, menu_id, lang_id)
        self.worker_thread.finished.connect(self.on_menu_fetched)
        self.worker_thread.start()

    def on_menu_fetched(self, menu_items, error):
        self.fetch_source_button.setEnabled(True)
        self.fetch_source_button.setText("Pobierz strukturę menu")
        if error:
            QMessageBox.critical(self, "Błąd API", f"Nie udało się pobrać menu:\n{error}")
            return
        if not menu_items:
            QMessageBox.information(self, "Informacja", "Nie znaleziono żadnych pozycji w tym menu.")
            return
        
        items_by_id = {item['item_id']: item for item in menu_items}
        children_by_parent_id = defaultdict(list)
        for item in menu_items:
            children_by_parent_id[item['parent_id']].append(item)
        for parent_id in children_by_parent_id:
            children_by_parent_id[parent_id].sort(key=lambda x: x['lang_data'][0].get('priority', 0))
        
        def add_children(parent_id, parent_widget):
            if parent_id not in children_by_parent_id: return
            for item_data in children_by_parent_id[parent_id]:
                item_id, lang_data = item_data['item_id'], item_data['lang_data'][0]
                tree_item = QTreeWidgetItem(parent_widget, [lang_data.get('name', ''), lang_data.get('item_textid', ''), str(item_id)])
                tree_item.setData(0, 100, item_data)
                add_children(item_id, tree_item)

        all_item_ids = set(items_by_id.keys())
        root_parent_ids = {p for p in children_by_parent_id if p not in all_item_ids}
        for root_id in sorted(list(root_parent_ids)):
             add_children(root_id, self.menu_tree)

    def run_process(self):
        if self.copy_all_checkbox.isChecked():
            self.run_process_all()
        else:
            self.run_process_single()

    def run_process_all(self):
        source_shop_id = self.source_shop_combo.currentData()
        source_menu_id = self.source_menu_combo.currentData()
        target_shop_id = self.target_shop_combo.currentData()
        target_menu_id = self.target_menu_combo.currentData()
        target_lang_id = self.target_lang_combo.currentData()

        msg = (f"Czy na pewno chcesz skopiować WSZYSTKIE przypisania produktów z:\n"
               f"Sklep ID: {source_shop_id}, Menu ID: {source_menu_id}\n\n"
               f"Do celu:\n"
               f"Sklep ID: {target_shop_id}, Menu ID: {target_menu_id}, Język: {target_lang_id}\n\n"
               f"Ten proces może potrwać bardzo długo!")
        
        reply = QMessageBox.question(self, "Potwierdzenie - Kopiowanie Całego Menu", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.accept()
        task_args = {
            'source_shop_id': source_shop_id,
            'source_menu_id': source_menu_id,
            'target_shop_id': target_shop_id,
            'target_menu_id': target_menu_id,
            'target_lang_id': target_lang_id,
        }
        self.start_background_task.emit(run_copy_all_assignments, [], task_args)

    def run_process_single(self):
        source_item = self.menu_tree.currentItem()
        if not source_item:
            QMessageBox.warning(self, "Błąd", "Wybierz kategorię źródłową z drzewa.")
            return

        source_item_data = source_item.data(0, 100)
        self.source_text_id = source_item_data['lang_data'][0].get('item_textid')
        if not self.source_text_id:
            QMessageBox.warning(self, "Błąd", "Wybrana kategoria nie ma 'item_textid' i nie może być użyta do mapowania.")
            return

        self.target_shop_id = self.target_shop_combo.currentData()
        self.target_menu_id = self.target_menu_combo.currentData()
        self.target_lang_id = self.target_lang_combo.currentData()
        
        self.run_button.setEnabled(False)
        self._show_progress("Krok 1/3: Wyszukiwanie kategorii docelowej", "Pobieranie menu docelowego...")

        self.worker_thread = TaskThread(get_menu_data, self.base_url, self.api_key, self.target_shop_id, self.target_menu_id, self.target_lang_id)
        self.worker_thread.finished.connect(self.on_target_menu_fetched)
        self.worker_thread.start()

    def on_target_menu_fetched(self, target_menu_items, error):
        if error:
            self.progress_dialog.close()
            QMessageBox.critical(self, "Błąd API", f"Nie udało się pobrać menu docelowego:\n{error}")
            self.run_button.setEnabled(True)
            return

        target_node = next((item for item in target_menu_items if item['lang_data'][0].get('item_textid') == self.source_text_id), None)
        if not target_node:
            self.progress_dialog.close()
            QMessageBox.critical(self, "Błąd mapowania", f"Nie znaleziono kategorii o ścieżce '{self.source_text_id}' w menu docelowym.")
            self.run_button.setEnabled(True)
            return
        
        self.target_node_id = target_node['item_id']
        
        self.progress_dialog.setLabelText("Krok 2/3: Zbieranie ID produktów ze źródła...")
        source_shop_id = self.source_shop_combo.currentData()
        source_menu_id = self.source_menu_combo.currentData()
        
        self.worker_thread = TaskThread(self._gather_product_ids, source_shop_id, source_menu_id, self.source_text_id)
        self.worker_thread.finished.connect(self.on_products_gathered)
        self.worker_thread.start()

    def _gather_product_ids(self, shop_id, menu_id, text_id):
        product_ids = []
        try:
            with open("produkty_menu_final.csv", 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if (row.get('shopId') == shop_id and
                        row.get('menuId') == menu_id and
                        row.get('menuItemTextId') == text_id):
                        product_ids.append(int(row['productId']))
        except FileNotFoundError:
            raise FileNotFoundError("Plik 'produkty_menu_final.csv' nie został znaleziony. Uruchom najpierw moduł 'Pobierz informacje o elementach menu'.")
        return product_ids

    def on_products_gathered(self, product_ids, error):
        self.progress_dialog.close()
        if error:
            QMessageBox.critical(self, "Błąd pliku", str(error))
            self.run_button.setEnabled(True)
            return
        
        if not product_ids:
            QMessageBox.information(self, "Informacja", "Nie znaleziono żadnych produktów przypisanych do wybranej kategorii źródłowej.")
            self.run_button.setEnabled(True)
            return

        msg = (f"Znaleziono {len(product_ids)} produktów do przypisania.\n\n"
               f"Źródło:\n- Kategoria: '{self.source_text_id}'\n\n"
               f"Cel:\n- Sklep ID: {self.target_shop_id}, Menu ID: {self.target_menu_id}\n"
               f"- ID Węzła: {self.target_node_id}\n\n"
               "Czy chcesz kontynuować?")
        
        reply = QMessageBox.question(self, "Potwierdzenie", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.accept()
            pinner_args = {
                "product_ids": product_ids,
                "target_shop_id": int(self.target_shop_id),
                "target_menu_id": int(self.target_menu_id),
                "target_node_id": self.target_node_id
            }
            self.start_background_task.emit(run_pinner_by_id, [], pinner_args)
        else:
            self.run_button.setEnabled(True)