"""Confirmar los nombres que la app dedujo de los rótulos del video.

La máquina PROPONE, la persona DISPONE. Poner un nombre propio en una
transcripción que va a publicarse es una decisión editorial, no un resultado
de cómputo: aquí se ve la evidencia de cada propuesta (qué rótulo, en qué
minuto, con qué confianza) y se acepta o se corrige una por una.

Por eso las propuestas de confianza BAJA llegan desmarcadas: hay que
mirarlas antes de aceptarlas, no al revés.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from videoindex.application.identificacion_service import ALTO, Identidad
from videoindex.application.transcript_export_service import marca_tiempo

_COLOR_CONFIANZA = {"ALTO": "#1b7f3b", "MEDIO": "#a06a00", "BAJO": "#a01b1b"}


class IdentidadesDialog(QDialog):
    def __init__(self, identidades: list[Identidad], n_rotulos: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nombres deducidos de los rótulos del video")
        self.resize(1000, 520)
        self._identidades = identidades

        con_nombre = [i for i in identidades if i.nombre]
        resumen = QLabel(
            f"Se leyeron <b>{n_rotulos} rótulos</b> en pantalla y se propone nombre para "
            f"<b>{len(con_nombre)}</b> de las {len(identidades)} voces detectadas.<br>"
            "Revisa cada fila: puedes editar el nombre haciendo doble clic. "
            "Las de confianza baja llegan <b>desmarcadas</b> a propósito."
        )
        resumen.setWordWrap(True)

        self._tabla = QTableWidget(len(identidades), 6)
        self._tabla.setHorizontalHeaderLabels(
            ["Usar", "Voz", "Nombre propuesto", "Función", "Confianza", "Evidencia"]
        )
        self._tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tabla.verticalHeader().setVisible(False)
        for fila, ident in enumerate(identidades):
            usar = QTableWidgetItem()
            usar.setFlags(usar.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            marcado = bool(ident.nombre) and ident.confianza == ALTO
            usar.setCheckState(Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked)
            self._tabla.setItem(fila, 0, usar)

            voz = QTableWidgetItem(
                f"{ident.speaker_label}  ({marca_tiempo(ident.primera_aparicion)})"
            )
            voz.setFlags(voz.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tabla.setItem(fila, 1, voz)

            # Editable: si el OCR leyó "MYRIAM" y falta el apellido, se completa aquí.
            self._tabla.setItem(fila, 2, QTableWidgetItem(ident.nombre or ""))

            funcion = ", ".join(x for x in (ident.funcion, ident.institucion) if x)
            if not funcion and ident.es_voz_en_off:
                funcion = "VOZ EN OFF / NARRACIÓN"
            item_funcion = QTableWidgetItem(funcion)
            item_funcion.setFlags(item_funcion.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tabla.setItem(fila, 3, item_funcion)

            conf = QTableWidgetItem(ident.confianza)
            conf.setFlags(conf.flags() & ~Qt.ItemFlag.ItemIsEditable)
            conf.setForeground(Qt.GlobalColor.black)
            conf.setToolTip(_COLOR_CONFIANZA.get(ident.confianza, ""))
            self._tabla.setItem(fila, 4, conf)

            evidencia = QTableWidgetItem(
                " | ".join(ident.evidencias) or "Sin evidencia en el video"
            )
            evidencia.setFlags(evidencia.flags() & ~Qt.ItemFlag.ItemIsEditable)
            evidencia.setToolTip("\n".join(ident.evidencias))
            self._tabla.setItem(fila, 5, evidencia)

        cabecera = self._tabla.horizontalHeader()
        cabecera.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for columna in (0, 1, 2, 3, 4):
            cabecera.setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)

        nota = QLabel(
            "<i>Lo que marques se guarda como el nombre de esa voz y se usará en la "
            "transcripción y en todo lo que exportes. Lo que dejes sin marcar seguirá "
            "apareciendo como voz sin identificar, que es preferible a un nombre "
            "equivocado.</i>"
        )
        nota.setWordWrap(True)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Save).setText("Guardar nombres")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(resumen)
        layout.addWidget(self._tabla, stretch=1)
        layout.addWidget(nota)
        layout.addWidget(botones)

    def nombres_confirmados(self) -> dict[str, str]:
        """speaker_label -> nombre, solo de las filas marcadas y con texto."""
        elegidos: dict[str, str] = {}
        for fila, ident in enumerate(self._identidades):
            marca = self._tabla.item(fila, 0)
            nombre = self._tabla.item(fila, 2)
            if marca and marca.checkState() == Qt.CheckState.Checked and nombre:
                texto = nombre.text().strip()
                if texto:
                    elegidos[ident.speaker_label] = texto
        return elegidos
