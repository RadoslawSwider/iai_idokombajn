
from PyQt6.QtWidgets import QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QVBoxLayout, QLabel

class NewModulesDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        self.source_shop_id_input = QLineEdit(self)
        self.source_menu_id_input = QLineEdit(self)
        self.dest_shop_id_input = QLineEdit(self)
        self.dest_menu_id_input = QLineEdit(self)
        self.dest_lang_id_input = QLineEdit(self)

        form_layout = QFormLayout()
        form_layout.addRow(QLabel("<b>Dane źródłowe:</b>"))
        form_layout.addRow("ID sklepu źródłowego:", self.source_shop_id_input)
        form_layout.addRow("ID menu źródłowego:", self.source_menu_id_input)
        form_layout.addRow(QLabel("<b>Dane docelowe:</b>"))
        form_layout.addRow("ID sklepu docelowego:", self.dest_shop_id_input)
        form_layout.addRow("ID menu docelowego:", self.dest_menu_id_input)
        form_layout.addRow("Język do aktualizacji (np. eng, cze):", self.dest_lang_id_input)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def get_data(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_shop_id_input.text(),
            self.source_menu_id_input.text(),
            self.dest_shop_id_input.text(),
            self.dest_menu_id_input.text(),
            self.dest_lang_id_input.text()
        )
