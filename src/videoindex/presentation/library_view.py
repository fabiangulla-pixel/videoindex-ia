"""Biblioteca e ingesta: agregar carpeta → resumen con ETA → confirmar → progreso."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from videoindex.application.time_estimator import TimeEstimator
from videoindex.config.settings import SETTINGS
from videoindex.presentation.workers import EscaneoWorker, PipelineWorker

_ETIQUETAS_ESTADO = {
    "pending": "⏳ pendiente",
    "transcribing": "🎙 transcribiendo",
    "segmenting": "✂ segmentando",
    "extracting": "🏷 entidades",
    "indexing": "📇 indexando",
    "completed": "✅ completado",
    "failed": "❌ falló",
}


class LibraryView(QWidget):
    # path, título, timestamp inicial (0 = desde el principio), video_id
    abrir_video = Signal(str, str, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boton_agregar = QPushButton("📂 Agregar carpeta…")
        self.progreso = QProgressBar()
        self.progreso.setVisible(False)
        self.etiqueta_estado = QLabel("")

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Título", "Curso", "Duración", "Estado"])
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.itemDoubleClicked.connect(self._abrir_seleccionado)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setPlaceholderText(
            "El registro de actividad (qué archivo se procesa, en qué etapa) aparece aquí…"
        )
        self.log.setFixedHeight(120)

        barra = QHBoxLayout()
        barra.addWidget(self.boton_agregar)
        barra.addWidget(self.etiqueta_estado, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.progreso)
        layout.addWidget(self.tabla, stretch=1)
        layout.addWidget(QLabel("Registro de actividad:"))
        layout.addWidget(self.log)

        self.boton_agregar.clicked.connect(self._agregar_carpeta)
        self._worker = None
        self.refrescar()

    def _registrar(self, mensaje: str) -> None:
        self.log.appendPlainText(mensaje)

    def refrescar(self):
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import VideoRepo

        con = conectar(paths.DB_PATH)
        try:
            videos = VideoRepo(con).listar()
        finally:
            con.close()
        self.tabla.setRowCount(len(videos))
        for fila, v in enumerate(videos):
            dur = TimeEstimator.humano(v.duration_seconds or 0)
            for col, texto in enumerate(
                [
                    v.title,
                    v.course_name or "—",
                    dur,
                    _ETIQUETAS_ESTADO.get(v.processing_status, v.processing_status),
                ]
            ):
                item = QTableWidgetItem(texto)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, (v.video_id, v.path))
                self.tabla.setItem(fila, col, item)

    def _abrir_seleccionado(self, item: QTableWidgetItem) -> None:
        """Reproducir cualquier video de la biblioteca, esté o no procesado
        (pedido explícito: no limitar la reproducción a resultados de
        búsqueda)."""
        fila = item.row()
        item_titulo = self.tabla.item(fila, 0)
        if item_titulo is None:
            return
        video_id, ruta = item_titulo.data(Qt.ItemDataRole.UserRole)
        self.abrir_video.emit(ruta, item_titulo.text(), 0.0, video_id)

    def _agregar_carpeta(self):
        if self._worker is not None and self._worker.isRunning():
            return  # guardia: ya hay un escaneo/lote en curso
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta con videos")
        if not carpeta:
            return
        self.etiqueta_estado.setText("Escaneando carpeta (checksums)…")
        self._registrar(f"Escaneando: {carpeta}")
        self.boton_agregar.setEnabled(False)  # guardia anti-doble-clic
        self.progreso.setVisible(True)
        self.progreso.setRange(0, 0)  # indeterminada hasta saber el total de archivos
        self._worker = EscaneoWorker(carpeta)
        self._worker.progreso.connect(self._on_progreso_escaneo)
        self._worker.terminado.connect(self._confirmar_lote)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _on_progreso_escaneo(self, indice: int, total: int, nombre: str):
        self.progreso.setRange(0, total)
        self.progreso.setValue(indice)
        self.etiqueta_estado.setText(f"Calculando checksum {indice}/{total}…")
        self._registrar(f"[{indice}/{total}] checksum: {nombre}")

    def _confirmar_lote(self, resultado):
        self.refrescar()
        self.progreso.setVisible(False)
        por_procesar = resultado.por_procesar
        if not por_procesar:
            self.etiqueta_estado.setText("Nada nuevo que procesar.")
            self._registrar("Escaneo terminado: nada nuevo que procesar.")
            self.boton_agregar.setEnabled(True)
            return

        estimador = TimeEstimator(SETTINGS.transcription.factor_tiempo_inicial)
        eta = estimador.eta_lote([v.duration_seconds or 0 for v in por_procesar])
        detalle = (
            f"Videos por procesar: {len(por_procesar)}\n"
            f"Material: {resultado.horas_totales:.1f} horas\n\n"
            f"Costo API: $0 (transcripción y embeddings 100% locales)\n"
            f"Tiempo estimado: ~{TimeEstimator.humano(eta)} "
            f"(whisper {SETTINGS.transcription.modelo}, CPU)\n\n"
            "¿Procesar ahora? Puedes cerrar la app a mitad: al relanzar se reanuda."
        )
        if (
            QMessageBox.question(self, "Confirmar procesamiento", detalle)
            != QMessageBox.StandardButton.Yes
        ):
            self.etiqueta_estado.setText("Lote registrado como pendiente (no procesado).")
            self.boton_agregar.setEnabled(True)
            return

        self.progreso.setVisible(True)
        self.progreso.setRange(0, 100)
        self._worker = PipelineWorker([v.video_id for v in por_procesar])
        self._worker.progreso.connect(self._on_progreso)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _on_progreso(self, video_id: str, etapa: str, fraccion: float):
        self.progreso.setValue(int(fraccion * 100))
        etiqueta = _ETIQUETAS_ESTADO.get(etapa, etapa)
        self.etiqueta_estado.setText(etiqueta)
        self._registrar(f"[{video_id[:8]}] {etiqueta}")
        self.refrescar()

    def _on_terminado(self, ok: int, fail: int):
        self.progreso.setVisible(False)
        self.etiqueta_estado.setText(f"Lote terminado: {ok} completados, {fail} fallidos.")
        self._registrar(f"Lote terminado: {ok} completados, {fail} fallidos.")
        self.boton_agregar.setEnabled(True)
        self.refrescar()

    def _error(self, mensaje: str):
        self.progreso.setVisible(False)
        self.boton_agregar.setEnabled(True)
        self._registrar(f"ERROR: {mensaje}")
        QMessageBox.critical(self, "Error", mensaje)
