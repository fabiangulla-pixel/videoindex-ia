"""Diálogo para añadir material desde una URL (YouTube y demás).

Acepta varias URLs, una por línea: es lo normal cuando se trabaja con una
serie de charlas o una mesa redonda partida en varios videos. Cada línea se
valida antes de empezar para no descubrir a mitad de descarga que una estaba
mal pegada.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from videoindex.infrastructure.media.youtube import es_url

AVISO_PERMISOS = (
    "Descarga solo material del que tengas autorización del titular: los "
    "términos de YouTube no la conceden por defecto, y publicar una "
    "transcripción exige además el permiso de quien habla."
)


class UrlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Añadir desde URL")
        self.setMinimumWidth(560)

        self._urls = QPlainTextEdit()
        self._urls.setPlaceholderText(
            "https://www.youtube.com/watch?v=…\n"
            "https://www.youtube.com/watch?v=…   (una URL por línea)"
        )
        self._urls.setFixedHeight(120)
        self._urls.textChanged.connect(self._validar)

        self._estado = QLabel("")
        self._estado.setWordWrap(True)

        self._con_imagen = QCheckBox(
            "Descargar también la imagen (necesaria para identificar hablantes por los rótulos)"
        )
        self._con_imagen.setToolTip(
            "Sin imagen no se pueden leer los rótulos sobreimpresos, que es de donde "
            "sale el nombre real de cada voz. Pesa más y tarda más en bajar."
        )

        explicacion = QLabel(
            "Por defecto se baja <b>solo la pista de audio</b>: es más rápido y "
            "suficiente para transcribir y buscar. El archivo queda en "
            "<code>data/descargas</code> y entra a la biblioteca con su título, canal "
            "y fecha de publicación reales, que son los datos que hacen falta para "
            "citar la fuente."
        )
        explicacion.setWordWrap(True)

        permisos = QLabel(f"<i>{AVISO_PERMISOS}</i>")
        permisos.setWordWrap(True)

        self._botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._botones.button(QDialogButtonBox.StandardButton.Ok).setText("Descargar")
        self._botones.accepted.connect(self.accept)
        self._botones.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>URLs del material:</b>"))
        layout.addWidget(self._urls)
        layout.addWidget(self._estado)
        layout.addWidget(self._con_imagen)
        layout.addWidget(explicacion)
        layout.addWidget(permisos)
        layout.addWidget(self._botones)

        self._validar()

    def urls(self) -> list[str]:
        """URLs válidas, sin duplicados y en el orden en que se pegaron."""
        vistas: list[str] = []
        for linea in self._urls.toPlainText().splitlines():
            limpia = linea.strip()
            if es_url(limpia) and limpia not in vistas:
                vistas.append(limpia)
        return vistas

    def con_imagen(self) -> bool:
        return self._con_imagen.isChecked()

    def _validar(self) -> None:
        lineas = [x.strip() for x in self._urls.toPlainText().splitlines() if x.strip()]
        validas = self.urls()
        invalidas = [x for x in lineas if not es_url(x)]
        self._botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(validas))
        if invalidas:
            self._estado.setText(
                f"⚠ {len(invalidas)} línea(s) no parecen una URL y se ignorarán: "
                f"{invalidas[0][:60]}…"
            )
        elif validas:
            self._estado.setText(f"{len(validas)} URL(s) listas para descargar.")
        else:
            self._estado.setText("Pega al menos una URL.")
