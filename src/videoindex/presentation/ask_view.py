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
from videoindex.config import paths
from videoindex.config.settings import MODELOS_POR_PROVEEDOR, SETTINGS
from videoindex.domain.models import Evidence, RAGAnswer
from videoindex.infrastructure.llm.providers import PROVEEDORES, crear_provider
from videoindex.presentation.workers import ServiciosCache, _crear_buscador


class EvidenciasWorker(QThread):
    listo = Signal(str, list)  # query, evidencias
    fallo = Signal(str)

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self):
        con = None
        try:
            from videoindex.infrastructure.db.connection import conectar

            servicios = ServiciosCache.obtener()
            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            rag = RAGService(_crear_buscador(servicios, con), SETTINGS.rag)
            evidencias = rag.recuperar_evidencias(self.query)
            self.listo.emit(self.query, evidencias)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


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
        con = None
        try:
            from videoindex.infrastructure.db.connection import conectar

            servicios = ServiciosCache.obtener()
            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            rag = RAGService(_crear_buscador(servicios, con), SETTINGS.rag)
            llm = crear_provider(self.proveedor, self.modelo)
            answer = rag.preguntar(self.query, self.evidencias, llm, self.proveedor)
            self.listo.emit(answer)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


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
        self.combo_modelo.clear()
        if proveedor == "lmstudio":
            # Sin catálogo fijo: se pregunta al servidor local qué modelo(s)
            # tiene cargados AHORA. Lista vacía = servidor no corriendo o sin
            # modelo cargado — el combo queda editable para escribirlo a mano.
            from videoindex.infrastructure.llm.providers import modelos_cargados_lmstudio

            modelos = modelos_cargados_lmstudio()
            if not modelos:
                self.combo_modelo.setPlaceholderText("LM Studio no responde (¿servidor iniciado?)")
            self.combo_modelo.addItems(modelos)
            return
        if proveedor == "ollama":
            # Igual que LM Studio: sin catálogo fijo, se pregunta a Ollama qué
            # tiene descargado con 'ollama pull' (pedir un modelo no instalado
            # da 404, no un error de red — antes el combo mostraba nombres
            # hardcodeados que podían no existir en la máquina del usuario).
            from videoindex.infrastructure.llm.providers import modelos_instalados_ollama

            modelos = modelos_instalados_ollama()
            if not modelos:
                self.combo_modelo.setPlaceholderText("Ollama no responde (¿servidor iniciado?)")
            self.combo_modelo.addItems(modelos)
            return
        self.combo_modelo.addItems(MODELOS_POR_PROVEEDOR.get(proveedor, []))

    def refrescar_proveedor_default(self) -> None:
        """Aplica el proveedor/modelo elegidos en el diálogo de Configuración,
        sin perder lo que el usuario haya escrito a mano en esta sesión si
        ya está preguntando con otro proveedor."""
        self.combo_proveedor.setCurrentText(SETTINGS.rag.proveedor)
        self.combo_modelo.setCurrentText(SETTINGS.rag.modelo)

    def _preguntar(self):
        # guardia anti-doble-disparo: returnPressed sigue activo aunque el
        # botón esté deshabilitado, así que se verifica el worker en curso.
        if self._worker is not None and self._worker.isRunning():
            return
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
        # Si el usuario deja el combo editable en blanco, se resuelve AQUÍ al
        # default del proveedor — el mismo valor que usará crear_provider()
        # más abajo. Antes, "" pasaba tal cual a estimar() (que la trata como
        # "modelo desconocido" y cotiza con el precio más caro) pero
        # crear_provider() sí aplicaba su propio default (más barato),
        # mostrando una estimación de costo que no correspondía a la llamada real.
        modelo = self.combo_modelo.currentText().strip() or PROVEEDORES[proveedor][1]

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

        from videoindex.infrastructure.db.connection import conectar

        servicios = ServiciosCache.obtener()
        con = conectar(paths.DB_PATH)
        try:
            rag = RAGService(_crear_buscador(servicios, con), SETTINGS.rag)
            estimacion = rag.estimar(query, evidencias, proveedor, modelo)
        except Exception as exc:
            con.close()
            self._error(str(exc))
            return
        con.close()

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
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import ChunkRepo

        e: Evidence = item.data(Qt.ItemDataRole.UserRole)
        con = conectar(paths.DB_PATH)
        try:
            fila = ChunkRepo(con).por_ids([e.chunk_id])
        finally:
            con.close()
        if fila:
            self._abrir_video(fila[0]["video_path"], e.video_title, e.start_time, e.video_id)

    def _error(self, mensaje: str):
        self.boton.setEnabled(True)
        self.estado.setText("")
        QMessageBox.critical(self, "Error", mensaje)
