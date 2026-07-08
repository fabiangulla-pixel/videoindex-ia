"""Selector de proyecto en la barra superior: agrupa videos por proyecto real
(antes solo existía course_name como texto libre sin uso en la GUI). "Todos
los proyectos" y "Sin proyecto" son opciones fijas; el resto viene de la
tabla `projects`. Crear uno nuevo solo pide un nombre."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

# Sentinels de UserRole para las opciones fijas del combo, para no
# confundirlas con un project_id real (que siempre es un uuid string).
# SIN_PROYECTO no puede ser None: LibraryView.filtrar_por_proyecto usa None
# para "Todos" (no filtra) y necesita distinguirlo de "sin proyecto" (filtra
# por project_id IS NULL) — VideoRepo.listar() sí espera None para ese caso,
# la traducción sentinel→None ocurre en _seleccion_cambiada.
TODOS = "__todos__"
SIN_PROYECTO = "__sin_proyecto__"
_NUEVO = "__nuevo__"


class NuevoProyectoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo proyecto")
        self.campo_nombre = QLineEdit()
        form = QFormLayout(self)
        form.addRow("Nombre:", self.campo_nombre)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def nombre(self) -> str:
        return self.campo_nombre.text().strip()


class ProjectSelector(QWidget):
    """Emite proyecto_cambiado(dato) con el mismo sentinel que espera
    VideoRepo.listar(project_id=...): TODOS ('__todos__', default, no
    filtra), None (filtra por project_id IS NULL), o un project_id real."""

    proyecto_cambiado = Signal(object)  # "__todos__" | None | str

    def __init__(self, parent=None):
        super().__init__(parent)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(220)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        self.combo.currentIndexChanged.connect(self._seleccion_cambiada)
        self.recargar()

    def recargar(self, seleccionar: str | None = TODOS) -> None:
        """Repuebla el combo desde la BD, preservando (o forzando) la
        selección activa."""
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import ProjectRepo

        con = conectar(paths.DB_PATH)
        try:
            proyectos = ProjectRepo(con).listar()
        finally:
            con.close()

        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("Todos los proyectos", TODOS)
        self.combo.addItem("Sin proyecto", SIN_PROYECTO)
        for p in proyectos:
            self.combo.addItem(p.name, p.project_id)
        self.combo.addItem("+ Nuevo proyecto…", _NUEVO)
        indice = self.combo.findData(seleccionar)
        self.combo.setCurrentIndex(indice if indice >= 0 else 0)
        self.combo.blockSignals(False)

    def proyecto_para_asignar(self) -> str | None:
        """Proyecto a asignar a videos NUEVOS al ingestar: None tanto si el
        filtro activo es 'Todos' como 'Sin proyecto' (en ningún caso hay un
        proyecto real que asignar), o el project_id si hay uno seleccionado."""
        dato = self.combo.currentData()
        return dato if dato not in (TODOS, SIN_PROYECTO) else None

    def _seleccion_cambiada(self, _indice: int) -> None:
        dato = self.combo.currentData()
        if dato == _NUEVO:
            self._crear_proyecto()
            return
        self.proyecto_cambiado.emit(None if dato == SIN_PROYECTO else dato)

    def _crear_proyecto(self) -> None:
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import ProjectRepo

        dialogo = NuevoProyectoDialog(self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or not dialogo.nombre():
            self.recargar(TODOS)  # cancelado: no dejar "+ Nuevo proyecto…" seleccionado
            return
        con = conectar(paths.DB_PATH)
        try:
            proyecto = ProjectRepo(con).crear(dialogo.nombre())
        finally:
            con.close()
        self.recargar(proyecto.project_id)
        self.proyecto_cambiado.emit(proyecto.project_id)
