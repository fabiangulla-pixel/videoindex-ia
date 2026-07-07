"""Diálogo de Configuración: API keys por proveedor + modelo/proveedor por
defecto para la pestaña Preguntar.

Adaptado del patrón de ReactivosFlow (api_settings_dialog.py): las claves
se guardan en el Credential Manager de Windows vía keyring, nunca en texto
plano ni en el repo. El proveedor/modelo por defecto (no es secreto) se
persiste aparte, en un JSON simple bajo data/ — ver config/settings.py.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from videoindex.config.settings import (
    MODELOS_POR_PROVEEDOR,
    SETTINGS,
    guardar_preferencias_rag,
    modelo_recomendado,
)
from videoindex.infrastructure.llm.secrets import delete_api_key, load_api_key, save_api_key

_NOMBRES_PROVEEDOR = {
    "gemini": "Gemini (recomendado)",
    "openai": "OpenAI",
    "claude": "Claude",
    "ollama": "Ollama (local, $0 — sin API key)",
}


class ApiSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración — API Keys y modelo por defecto")
        self.setMinimumWidth(480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form_key = QFormLayout()
        self._proveedor_key = QComboBox()
        for prov, nombre in _NOMBRES_PROVEEDOR.items():
            self._proveedor_key.addItem(nombre, prov)
        self._proveedor_key.currentIndexChanged.connect(self._cargar_key)
        form_key.addRow("Proveedor:", self._proveedor_key)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("sk-… / AIza… (se guarda en el Credential Manager de Windows)")
        form_key.addRow("Clave API:", self._key)

        self._estado_key = QLabel("")
        form_key.addRow("", self._estado_key)

        guardar_btn = QPushButton("Guardar clave")
        guardar_btn.clicked.connect(self._guardar_key)
        borrar_btn = QPushButton("Borrar clave")
        borrar_btn.clicked.connect(self._borrar_key)
        form_key.addRow(guardar_btn, borrar_btn)

        layout.addLayout(form_key)

        layout.addWidget(QLabel(""))
        layout.addWidget(QLabel("<b>Proveedor y modelo por defecto para Preguntar:</b>"))

        form_default = QFormLayout()
        self._proveedor_default = QComboBox()
        for prov, nombre in _NOMBRES_PROVEEDOR.items():
            self._proveedor_default.addItem(nombre, prov)
        self._proveedor_default.setCurrentIndex(
            self._proveedor_default.findData(SETTINGS.rag.proveedor)
        )
        self._proveedor_default.currentIndexChanged.connect(self._repoblar_modelos_default)
        form_default.addRow("Proveedor por defecto:", self._proveedor_default)

        self._modelo_default = QComboBox()
        self._modelo_default.setEditable(True)  # modelos nuevos sin recompilar
        form_default.addRow("Modelo por defecto:", self._modelo_default)
        layout.addLayout(form_default)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        botones.accepted.connect(self._guardar_default_y_cerrar)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._cargar_key(0)
        self._repoblar_modelos_default(preservar_actual=True)

    def _cargar_key(self, _idx=None):
        proveedor = self._proveedor_key.currentData()
        if proveedor == "ollama":
            self._key.setEnabled(False)
            self._key.clear()
            self._estado_key.setText("Ollama es local: no necesita API key.")
            return
        self._key.setEnabled(True)
        key = load_api_key(proveedor) or ""
        self._key.setText(key)
        self._estado_key.setText(
            "Clave guardada en el Credential Manager." if key else "Sin clave guardada."
        )

    def _guardar_key(self):
        proveedor = self._proveedor_key.currentData()
        key = self._key.text().strip()
        if proveedor == "ollama":
            return
        if not key:
            self._estado_key.setText("Escribe una clave antes de guardar.")
            return
        save_api_key(proveedor, key)
        self._estado_key.setText("Clave guardada.")

    def _borrar_key(self):
        proveedor = self._proveedor_key.currentData()
        if proveedor == "ollama":
            return
        delete_api_key(proveedor)
        self._key.clear()
        self._estado_key.setText("Clave eliminada.")

    def _repoblar_modelos_default(self, _idx=None, preservar_actual: bool = False):
        proveedor = self._proveedor_default.currentData()
        self._modelo_default.clear()
        self._modelo_default.addItems(MODELOS_POR_PROVEEDOR.get(proveedor, []))
        if preservar_actual and SETTINGS.rag.proveedor == proveedor:
            self._modelo_default.setCurrentText(SETTINGS.rag.modelo)
        else:
            self._modelo_default.setCurrentText(modelo_recomendado(proveedor))

    def _guardar_default_y_cerrar(self):
        proveedor = self._proveedor_default.currentData()
        modelo = self._modelo_default.currentText().strip() or modelo_recomendado(proveedor)
        guardar_preferencias_rag(proveedor, modelo)
        self.accept()
