"""Pestaña Preguntar: RAG con confirmación de costo y citas clicables."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from videoindex.application.rag_service import RAGService, _fmt_tiempo
from videoindex.config.settings import SETTINGS
from videoindex.domain.models import Evidence, RAGAnswer
from videoindex.infrastructure.llm.providers import PROVEEDORES, crear_provider
from videoindex.presentation.workers import ServiciosCache


class EvidenciasWorker(QThread):
    listo = Signal(str, list)  # query, evidencias
    fallo = Signal(str)

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self):
        try:
            servicios = ServiciosCache.obtener()
            rag = RAGService(servicios.buscador, SETTINGS.rag)
            self.listo.emit(self.query, rag.recuperar_evidencias(self.query))
        except Exception as exc:
            self.fallo.emit(str(exc))


class PreguntaWorker(QThread):
    listo = Signal(object)  # RAGAnswer
    fallo = Signal(str)

    def __init__(self, query: str, evidencias: list, proveedor: str, modelo: str):
        super().__init__()
        self.query = query
        self.evidencias = evidencias
        self.proveedor = proveedor
        self.modelo = modelo

    def run(self):
        try:
            servicios = ServiciosCache.obtener()
            rag = RAGService(servicios.buscador, SETTINGS.rag)
            llm = crear_provider(self.proveedor, self.modelo)
            self.listo.emit(rag.preguntar(self.query, self.evidencias, llm, self.proveedor))
        except Exception as exc:
            self.fallo.emit(str(exc))


class AskView(QWidget):
    def __init__(self, abrir_video, parent=None):
        """abrir_video: callable(path, titulo, start_time) — normalmente el player."""
        super().__init__(parent)
        self._abrir_video = abrir_video

        self.combo_proveedor = QComboBox()
        self.combo_proveedor.addItems(sorted(PROVEEDORES))
        self.combo_proveedor.setCurrentText(SETTINGS.rag.proveedor)
        self.combo_modelo = QComboBox()
        self.combo_modelo.setEditable(True)  # modelos nuevos sin recompilar
        self.combo_proveedor.currentTextChanged.connect(self._modelos_del_proveedor)
        self._modelos_del_proveedor(self.combo_proveedor.currentText())

        self.caja = QLineEdit()
        self.caja.setPlaceholderText("Pregunta sobre tu biblioteca de videos…")
        self.boton = QPushButton("💬 Preguntar")
        self.estado = QLabel("")
        self.respuesta = QTextBrowser()
        self.fuentes = QListWidget()
        self.fuentes.setMaximumHeight(140)
        self.costo = QLabel("")

        fila_modelo = QHBoxLayout()
        fila_modelo.addWidget(QLabel("Proveedor:"))
        fila_modelo.addWidget(self.combo_proveedor)
        fila_modelo.addWidget(QLabel("Modelo:"))
        fila_modelo.addWidget(self.combo_modelo, stretch=1)

        fila_pregunta = QHBoxLayout()
        fila_pregunta.addWidget(self.caja, stretch=1)
        fila_pregunta.addWidget(self.boton)

        layout = QVBoxLayout(self)
        layout.addLayout(fila_modelo)
        layout.addLayout(fila_pregunta)
        layout.addWidget(self.estado)
        layout.addWidget(self.respuesta, stretch=1)
        layout.addWidget(QLabel("Fuentes (clic para abrir el video en ese instante):"))
        layout.addWidget(self.fuentes)
        layout.addWidget(self.costo)

        self.boton.clicked.connect(self._preguntar)
        self.caja.returnPressed.connect(self._preguntar)
        self.fuentes.itemClicked.connect(self._abrir_fuente)
        self._worker = None

    def _modelos_del_proveedor(self, proveedor: str):
        defaults = {
            "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            "openai": ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-4.1-mini"],
            "claude": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
            "ollama": ["llama3.1", "qwen2.5", "mistral"],
        }
        self.combo_modelo.clear()
        self.combo_modelo.addItems(defaults.get(proveedor, []))

    def _preguntar(self):
        query = self.caja.text().strip()
        if not query:
            return
        self.boton.setEnabled(False)  # guardia anti-doble-clic
        self.estado.setText("Buscando evidencia en tu biblioteca…")
        self._worker = EvidenciasWorker(query)
        self._worker.listo.connect(self._confirmar_costo)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _confirmar_costo(self, query: str, evidencias: list):
        proveedor = self.combo_proveedor.currentText()
        modelo = self.combo_modelo.currentText().strip()

        if not evidencias:
            # Gate de evidencia: cero llamadas al LLM, cero costo, cero alucinación.
            self.estado.setText("")
            self.respuesta.setPlainText(
                "No hay evidencia suficiente en tu biblioteca para esta pregunta."
            )
            self.fuentes.clear()
            self.costo.setText("Costo: $0 (no se llamó a la IA: sin evidencia)")
            self.boton.setEnabled(True)
            return

        servicios = ServiciosCache.obtener()
        rag = RAGService(servicios.buscador, SETTINGS.rag)
        estimacion = rag.estimar(query, evidencias, proveedor, modelo)

        # Estándar de costo IA: confirmación previa SIEMPRE que haya gasto.
        if not estimacion.es_local and (
            QMessageBox.question(
                self,
                "Confirmar gasto de IA",
                estimacion.resumen(),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            self.estado.setText("Pregunta cancelada (no se gastó nada).")
            self.boton.setEnabled(True)
            return

        self.estado.setText(f"Preguntando a {modelo}…")
        self._worker = PreguntaWorker(query, evidencias, proveedor, modelo)
        self._worker.listo.connect(self._mostrar)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _mostrar(self, answer: RAGAnswer):
        self.boton.setEnabled(True)
        self.estado.setText("")
        texto = answer.text
        if answer.evidences and not answer.anclada:
            texto = "⚠ Respuesta sin anclaje en evidencia (no cita ninguna fuente):\n\n" + texto
        self.respuesta.setPlainText(texto)

        self.fuentes.clear()
        for i, e in enumerate(answer.evidences, 1):
            marca = "★" if i in answer.cited_indices else "·"
            item = QListWidgetItem(f"{marca} [{i}] {e.video_title} — {_fmt_tiempo(e.start_time)}")
            item.setData(Qt.ItemDataRole.UserRole, e)
            self.fuentes.addItem(item)

        if answer.cost_usd is not None:
            self.costo.setText(
                f"Costo real: ${answer.cost_usd:,.4f} USD "
                f"({answer.tokens_in:,} in / {answer.tokens_out:,} out)"
            )

    def _abrir_fuente(self, item: QListWidgetItem):
        e: Evidence = item.data(Qt.ItemDataRole.UserRole)
        # Ruta del video vía el chunk (Evidence no la carga; la resuelve el buscador)
        servicios = ServiciosCache.obtener()
        fila = servicios.buscador.chunks.por_ids([e.chunk_id])
        if fila:
            self._abrir_video(fila[0]["video_path"], e.video_title, e.start_time)

    def _error(self, mensaje: str):
        self.boton.setEnabled(True)
        self.estado.setText("")
        QMessageBox.critical(self, "Error", mensaje)
