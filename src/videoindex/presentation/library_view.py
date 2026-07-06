"""Biblioteca e ingesta: agregar carpeta → resumen con ETA → confirmar → progreso."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from videoindex.application.time_estimator import TimeEstimator
from videoindex.config.settings import SETTINGS
from videoindex.presentation.workers import EscaneoWorker, PipelineWorker, ServiciosCache

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

        barra = QHBoxLayout()
        barra.addWidget(self.boton_agregar)
        barra.addWidget(self.etiqueta_estado, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.progreso)
        layout.addWidget(self.tabla, stretch=1)

        self.boton_agregar.clicked.connect(self._agregar_carpeta)
        self._worker = None
        self.refrescar()

    def refrescar(self):
        from videoindex.infrastructure.db.repositories import VideoRepo

        servicios = ServiciosCache.obtener()
        videos = VideoRepo(servicios.con).listar()
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
                    item.setData(Qt.ItemDataRole.UserRole, v.video_id)
                self.tabla.setItem(fila, col, item)

    def _agregar_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta con videos")
        if not carpeta:
            return
        self.etiqueta_estado.setText("Escaneando carpeta (checksums)…")
        self.boton_agregar.setEnabled(False)  # guardia anti-doble-clic
        self._worker = EscaneoWorker(carpeta)
        self._worker.terminado.connect(self._confirmar_lote)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _confirmar_lote(self, resultado):
        self.refrescar()
        por_procesar = resultado.por_procesar
        if not por_procesar:
            self.etiqueta_estado.setText("Nada nuevo que procesar.")
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

    def _on_progreso(self, _video_id: str, etapa: str, fraccion: float):
        self.progreso.setValue(int(fraccion * 100))
        self.etiqueta_estado.setText(_ETIQUETAS_ESTADO.get(etapa, etapa))
        self.refrescar()

    def _on_terminado(self, ok: int, fail: int):
        self.progreso.setVisible(False)
        self.etiqueta_estado.setText(f"Lote terminado: {ok} completados, {fail} fallidos.")
        self.boton_agregar.setEnabled(True)
        self.refrescar()

    def _error(self, mensaje: str):
        self.progreso.setVisible(False)
        self.boton_agregar.setEnabled(True)
        QMessageBox.critical(self, "Error", mensaje)
