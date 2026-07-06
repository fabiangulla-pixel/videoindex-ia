"""Búsqueda híbrida: tarjetas-evidencia con salto al video."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videoindex.domain.models import SearchResult
from videoindex.presentation.workers import BusquedaWorker


def _fmt(segundos: float) -> str:
    s = int(segundos)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class SearchView(QWidget):
    abrir_video = Signal(str, str, float)  # path, titulo, start_time

    def __init__(self, parent=None):
        super().__init__(parent)
        self.caja = QLineEdit()
        self.caja.setPlaceholderText("Buscar un concepto, definición, ejemplo…")
        self.boton = QPushButton("🔍 Buscar")
        self.estado = QLabel("")
        self.lista = QListWidget()
        self.lista.setWordWrap(True)

        barra = QHBoxLayout()
        barra.addWidget(self.caja, stretch=1)
        barra.addWidget(self.boton)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.estado)
        layout.addWidget(self.lista, stretch=1)

        self.boton.clicked.connect(self._buscar)
        self.caja.returnPressed.connect(self._buscar)
        self.lista.itemClicked.connect(self._abrir)
        self._worker = None

    def _buscar(self):
        query = self.caja.text().strip()
        if not query:
            return
        self.estado.setText("Buscando… (la primera búsqueda carga los modelos)")
        self.boton.setEnabled(False)
        self._worker = BusquedaWorker(query)
        self._worker.resultados.connect(self._mostrar)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _mostrar(self, resultados: list[SearchResult]):
        self.boton.setEnabled(True)
        self.lista.clear()
        if not resultados:
            self.estado.setText("Sin resultados en tu biblioteca.")
            return
        self.estado.setText(f"{len(resultados)} resultados (clic para abrir el video en ese punto)")
        for r in resultados:
            b = r.breakdown
            texto = (
                f"▶ {r.video_title}   {_fmt(r.start_time)}–{_fmt(r.end_time)}   "
                f"score {r.score:.2f}\n{r.snippet}"
            )
            item = QListWidgetItem(texto)
            item.setToolTip(
                f"semántico {b.semantico:.2f} · textual {b.textual:.2f} · "
                f"entidades {b.entidades:.2f} · confianza {b.confianza:.2f}"
            )
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.lista.addItem(item)

    def _abrir(self, item: QListWidgetItem):
        r: SearchResult = item.data(Qt.ItemDataRole.UserRole)
        self.abrir_video.emit(r.video_path, r.video_title, r.start_time)

    def _error(self, mensaje: str):
        self.boton.setEnabled(True)
        self.estado.setText("")
        QMessageBox.critical(self, "Error de búsqueda", mensaje)
