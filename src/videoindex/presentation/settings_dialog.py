"""Diálogo de Configuración, en dos pestañas:

- IA en la nube: API keys por proveedor + modelo/proveedor por defecto para
  Preguntar. Adaptado del patrón de ReactivosFlow (api_settings_dialog.py):
  las claves se guardan en el Credential Manager de Windows vía keyring,
  nunca en texto plano ni en el repo.
- Transcripción y voces: qué modelo de Whisper usar y cómo separar
  hablantes. Todo local ($0), así que aquí no hay claves ni costos: lo que
  se decide es cuánto tiempo de CPU cuesta y con cuánta precisión.

Lo que no es secreto (proveedor/modelo, ajustes de transcripción) se
persiste en un JSON simple bajo data/ — ver config/settings.py.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from videoindex.config.settings import (
    FACTOR_TIEMPO_POR_MODELO,
    MODELOS_POR_PROVEEDOR,
    MODELOS_WHISPER,
    SETTINGS,
    guardar_preferencias_rag,
    guardar_preferencias_transcripcion,
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
        self.setWindowTitle("Configuración")
        self.setMinimumWidth(560)
        self._build_ui()

    def _build_ui(self):
        raiz = QVBoxLayout(self)
        pestanas = QTabWidget()
        pestanas.addTab(self._pestana_ia(), "☁ IA en la nube")
        pestanas.addTab(self._pestana_transcripcion(), "🎙 Transcripción y voces")
        raiz.addWidget(pestanas)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        botones.accepted.connect(self._guardar_y_cerrar)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

        self._cargar_key(0)
        self._repoblar_modelos_default(preservar_actual=True)

    def _pestana_ia(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)

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
        layout.addStretch(1)
        return pagina

    def _pestana_transcripcion(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)

        intro = QLabel(
            "Todo lo de esta pestaña corre en tu equipo: <b>$0 de API</b>. "
            "Lo que se decide aquí es cuánto tarda y con cuánta precisión."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self._modelo_whisper = QComboBox()
        for nombre in MODELOS_WHISPER:
            factor = FACTOR_TIEMPO_POR_MODELO.get(nombre, 1.0)
            self._modelo_whisper.addItem(f"{nombre}  (~{factor:.2g}× el tiempo del audio)", nombre)
        indice = self._modelo_whisper.findData(SETTINGS.transcription.modelo)
        if indice >= 0:
            self._modelo_whisper.setCurrentIndex(indice)
        form.addRow("Modelo de Whisper:", self._modelo_whisper)

        guia = QLabel(
            "<i>small</i> alcanza para buscar dentro del material. Para un texto que "
            "vas a <b>publicar</b>, usa <i>large-v3-turbo</i>: acierta mucho más en "
            "nombres propios y terminología, que es justo lo que después habría que "
            "corregir a mano."
        )
        guia.setWordWrap(True)

        self._idioma = QLineEdit(SETTINGS.transcription.idioma)
        self._idioma.setMaximumWidth(80)
        self._idioma.setToolTip("Código ISO: es, en, pt, fr…")
        form.addRow("Idioma:", self._idioma)
        layout.addLayout(form)
        layout.addWidget(guia)

        layout.addWidget(QLabel("<b>Separación de voces (quién dice qué)</b>"))
        self._diarizacion = QCheckBox("Distinguir hablantes al procesar")
        self._diarizacion.setChecked(SETTINGS.diarization.activa)
        self._diarizacion.toggled.connect(self._alternar_diarizacion)
        layout.addWidget(self._diarizacion)

        form_voces = QFormLayout()
        self._n_hablantes = QSpinBox()
        self._n_hablantes.setRange(0, 20)
        self._n_hablantes.setValue(SETTINGS.diarization.n_hablantes)
        self._n_hablantes.setSpecialValueText("automático")
        self._n_hablantes.valueChanged.connect(self._alternar_diarizacion)
        form_voces.addRow("Número de hablantes:", self._n_hablantes)

        self._umbral = QDoubleSpinBox()
        self._umbral.setRange(0.05, 1.50)
        self._umbral.setSingleStep(0.05)
        self._umbral.setDecimals(2)
        self._umbral.setValue(SETTINGS.diarization.umbral_distancia)
        form_voces.addRow("Umbral automático:", self._umbral)
        layout.addLayout(form_voces)

        self._nota_voces = QLabel("")
        self._nota_voces.setWordWrap(True)
        layout.addWidget(self._nota_voces)
        layout.addStretch(1)

        self._alternar_diarizacion()
        return pagina

    def _alternar_diarizacion(self, *_args) -> None:
        activa = self._diarizacion.isChecked()
        automatico = self._n_hablantes.value() == 0
        self._n_hablantes.setEnabled(activa)
        self._umbral.setEnabled(activa and automatico)
        if not activa:
            self._nota_voces.setText(
                "Sin separación de voces la transcripción sale corrida, sin saber "
                "quién habla en cada momento."
            )
        elif automatico:
            self._nota_voces.setText(
                "En automático el número de voces sale del <b>umbral</b>: más alto funde "
                "voces distintas, más bajo inventa hablantes de más. Es una heurística "
                "sin calibrar con tus grabaciones — <b>si sabes cuántas personas hablan "
                "(una entrevista son 2), ponlo aquí</b>: es bastante más fiable."
            )
        else:
            self._nota_voces.setText(
                f"Se agruparán las voces en exactamente {self._n_hablantes.value()} "
                "hablantes. El umbral no se usa en este modo."
            )

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

    def _guardar_y_cerrar(self):
        """Guarda las DOS pestañas: se llega aquí desde un único botón
        Guardar, y que una pestaña se perdiera por haber tocado la otra sería
        el fallo más fácil de cometer (por eso las preferencias se mezclan en
        el JSON en vez de reemplazarlo)."""
        proveedor = self._proveedor_default.currentData()
        modelo = self._modelo_default.currentText().strip() or modelo_recomendado(proveedor)
        guardar_preferencias_rag(proveedor, modelo)
        guardar_preferencias_transcripcion(
            self._modelo_whisper.currentData(),
            self._idioma.text().strip() or "es",
            self._diarizacion.isChecked(),
            self._n_hablantes.value(),
            self._umbral.value(),
        )
        self.accept()
