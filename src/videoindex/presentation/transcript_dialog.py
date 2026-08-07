"""Transcripción por hablantes: leerla, ponerle nombre a cada voz y exportarla.

Es la ventana donde la diarización deja de ser un dato técnico y se vuelve
utilizable: "SPEAKER_00" pasa a ser "Marta Ríos" y cada intervención se puede
oír en su minuto exacto para verificarla antes de publicarla.

El renombrado se guarda al vuelo en la BD (tabla video_speakers), no al
cerrar: si la ventana se cierra sin querer, el trabajo de nombrar no se
pierde. La transcripción en sí NUNCA se edita aquí — es el registro
inmutable de lo que dijo el modelo; la corrección se hace sobre el .docx
exportado, que es donde vive el trabajo editorial.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from videoindex.application import transcript_export_service as export
from videoindex.config import paths
from videoindex.domain.diarization import nombre_visible
from videoindex.infrastructure.db.connection import conectar
from videoindex.infrastructure.db.repositories import SpeakerRepo


class TranscriptDialog(QDialog):
    saltar_a = Signal(float)  # segundo al que debe ir el reproductor

    def __init__(self, video_id: str, titulo: str, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.setWindowTitle(f"Transcripción y hablantes — {titulo}")
        self.resize(900, 640)
        self._campos: dict[str, QLineEdit] = {}

        self._tabla = QTableWidget(0, 3)
        self._tabla.setHorizontalHeaderLabels(["Minuto", "Hablante", "Intervención"])
        self._tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tabla.setWordWrap(True)
        self._tabla.horizontalHeader().setStretchLastSection(True)
        self._tabla.setColumnWidth(0, 80)
        self._tabla.setColumnWidth(1, 160)
        self._tabla.itemDoubleClicked.connect(self._saltar)

        self._grupo_hablantes = QGroupBox("Nombres de los hablantes")
        self._form_hablantes = QFormLayout(self._grupo_hablantes)

        self._con_timestamps = QCheckBox("Incluir marcas de tiempo al exportar")
        self._con_timestamps.setChecked(True)

        boton_docx = QPushButton("📄 Exportar Word…")
        boton_docx.setToolTip("Documento con estilos, para corregir y entregar")
        boton_md = QPushButton("📝 Exportar Markdown…")
        boton_srt = QPushButton("💬 Exportar subtítulos…")
        boton_docx.clicked.connect(lambda: self._exportar("docx"))
        boton_md.clicked.connect(lambda: self._exportar("md"))
        boton_srt.clicked.connect(lambda: self._exportar("srt"))

        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)

        barra = QHBoxLayout()
        barra.addWidget(self._con_timestamps)
        barra.addStretch(1)
        barra.addWidget(boton_docx)
        barra.addWidget(boton_md)
        barra.addWidget(boton_srt)
        barra.addWidget(cerrar)

        self._ayuda = QLabel("")
        self._ayuda.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._grupo_hablantes)
        layout.addWidget(self._ayuda)
        layout.addWidget(self._tabla, stretch=1)
        layout.addLayout(barra)

        self._cargar()

    # ---- datos -------------------------------------------------------

    def _cargar(self) -> None:
        con = conectar(paths.DB_PATH)
        try:
            datos = export.preparar(con, self.video_id)
            etiquetas = SpeakerRepo(con).etiquetas_detectadas(self.video_id)
        except ValueError as exc:
            QMessageBox.information(self, "Transcripción", str(exc))
            self._ayuda.setText(str(exc))
            return
        finally:
            con.close()

        self._poblar_hablantes(etiquetas, datos.nombres)
        self._poblar_tabla(datos)

        if etiquetas:
            self._ayuda.setText(
                f"Se distinguieron <b>{len(etiquetas)} voces</b>. Ponles nombre arriba y se "
                "usará en la tabla y en todo lo que exportes. Doble clic en una "
                "intervención para oírla en el reproductor y verificarla."
            )
        else:
            self._ayuda.setText(
                "Este video no tiene etiquetas de hablante: se procesó con la "
                "diarización desactivada, o falló. Actívala en Configuración → "
                "Transcripción y vuelve a procesarlo para separar las voces."
            )

    def _poblar_hablantes(self, etiquetas: list[str], nombres: dict[str, str]) -> None:
        while self._form_hablantes.rowCount():
            self._form_hablantes.removeRow(0)
        self._campos.clear()
        for etiqueta in etiquetas:
            campo = QLineEdit(nombres.get(etiqueta, ""))
            campo.setPlaceholderText(f"Nombre real de {etiqueta} (vacío = dejar la etiqueta)")
            campo.editingFinished.connect(lambda e=etiqueta: self._renombrar(e))
            self._campos[etiqueta] = campo
            self._form_hablantes.addRow(f"{etiqueta}:", campo)
        self._grupo_hablantes.setVisible(bool(etiquetas))

    def _poblar_tabla(self, datos: export.TranscripcionExportable) -> None:
        self._tabla.setRowCount(len(datos.intervenciones))
        for fila, intervencion in enumerate(datos.intervenciones):
            marca = export.marca_tiempo(intervencion.start_time)
            quien = nombre_visible(intervencion.speaker, datos.nombres)
            for columna, texto in enumerate([marca, quien, intervencion.texto]):
                item = QTableWidgetItem(texto)
                if columna == 0:
                    item.setData(Qt.ItemDataRole.UserRole, intervencion.start_time)
                self._tabla.setItem(fila, columna, item)
        self._tabla.resizeRowsToContents()

    def _renombrar(self, etiqueta: str) -> None:
        campo = self._campos.get(etiqueta)
        if campo is None:
            return
        con = conectar(paths.DB_PATH)
        try:
            SpeakerRepo(con).renombrar(self.video_id, etiqueta, campo.text())
            datos = export.preparar(con, self.video_id)
        finally:
            con.close()
        self._poblar_tabla(datos)  # la columna "Hablante" refleja el nombre nuevo

    # ---- acciones ----------------------------------------------------

    def _saltar(self, item: QTableWidgetItem) -> None:
        celda = self._tabla.item(item.row(), 0)
        if celda is None:
            return
        segundo = celda.data(Qt.ItemDataRole.UserRole)
        if segundo is not None:
            self.saltar_a.emit(float(segundo))

    def _exportar(self, formato: str) -> None:
        etiqueta, funcion = export.FORMATOS[formato]
        nombre_base = "".join(
            c if c.isalnum() or c in " _-." else "_" for c in self.windowTitle().split("— ")[-1]
        )
        destino, _ = QFileDialog.getSaveFileName(
            self,
            f"Exportar transcripción — {etiqueta}",
            f"{nombre_base}.{formato}",
            f"{etiqueta} (*.{formato})",
        )
        if not destino:
            return
        con = conectar(paths.DB_PATH)
        try:
            if formato == "srt":
                ruta = funcion(con, self.video_id, destino)
            else:
                ruta = funcion(con, self.video_id, destino, self._con_timestamps.isChecked())
        except Exception as exc:
            QMessageBox.critical(self, "Exportar transcripción", str(exc))
            return
        finally:
            con.close()
        QMessageBox.information(
            self,
            "Transcripción exportada",
            f"Guardada en:\n{Path(ruta)}\n\n{export.ADVERTENCIA}",
        )
