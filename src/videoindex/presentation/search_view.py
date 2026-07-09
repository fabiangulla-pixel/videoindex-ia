"""Búsqueda híbrida: tarjetas-evidencia con salto al video."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
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

# "Todos" no es ilimitado: un techo alto (ver SearchEngine.search — sube
# candidatos_por_fuente hasta este k) para no inundar la lista con miles de
# ítems si el corpus crece mucho.
_OPCIONES_CANTIDAD = [("10", 10), ("25", 25), ("50", 50), ("Todos", 500)]


def _fmt(segundos: float) -> str:
    s = int(segundos)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class SearchView(QWidget):
    abrir_video = Signal(str, str, float, str)  # path, titulo, start_time, video_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.caja = QLineEdit()
        self.caja.setPlaceholderText(
            'p. ej. "cómo se entrena un modelo con los datos de la empresa"'
        )
        self.combo_cantidad = QComboBox()
        for etiqueta, _valor in _OPCIONES_CANTIDAD:
            self.combo_cantidad.addItem(etiqueta)
        self.combo_cantidad.setCurrentIndex(0)  # 10, mismo comportamiento de antes
        self.boton = QPushButton("🔍 Buscar")
        self.estado = QLabel("")
        # Una palabra suelta y muy frecuente en el video (p. ej. "datos" en
        # una charla sobre IA) no discrimina: casi todos los chunks la
        # mencionan y se parecen semánticamente entre sí. Una frase describe
        # LA IDEA, no solo una palabra, y ahí la búsqueda semántica sí rinde.
        self.pista = QLabel(
            "💡 Mejor una frase que describa la idea que buscas que una sola palabra "
            "(las palabras sueltas muy comunes en el video no ayudan a discriminar)."
        )
        self.pista.setStyleSheet("color: gray; font-size: 11px;")
        self.pista.setWordWrap(True)
        self.lista = QListWidget()
        self.lista.setWordWrap(True)

        barra = QHBoxLayout()
        barra.addWidget(self.caja, stretch=1)
        barra.addWidget(QLabel("Mostrar:"))
        barra.addWidget(self.combo_cantidad)
        barra.addWidget(self.boton)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.pista)
        layout.addWidget(self.estado)
        layout.addWidget(self.lista, stretch=1)

        self.boton.clicked.connect(self._buscar)
        self.caja.returnPressed.connect(self._buscar)
        self.lista.itemClicked.connect(self._abrir)
        self._worker = None
        # Cada proyecto es un corpus aparte: mismo sentinel que
        # VideoRepo.listar ("__todos__" = toda la biblioteca). Lo setea
        # MainWindow al cambiar el selector de proyecto.
        self.proyecto_activo: str | None = "__todos__"

    def filtrar_por_proyecto(self, project_id: str | None) -> None:
        """Conectado a ProjectSelector.proyecto_cambiado."""
        self.proyecto_activo = project_id

    def _buscar(self):
        # guardia anti-doble-disparo: returnPressed sigue activo aunque el
        # botón esté deshabilitado, así que se verifica el worker en curso.
        if self._worker is not None and self._worker.isRunning():
            return
        query = self.caja.text().strip()
        if not query:
            return
        self.estado.setText("Buscando… (la primera búsqueda carga los modelos)")
        self.boton.setEnabled(False)
        k = _OPCIONES_CANTIDAD[self.combo_cantidad.currentIndex()][1]
        self._worker = BusquedaWorker(query, k, self.proyecto_activo)
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
        self.abrir_video.emit(r.video_path, r.video_title, r.start_time, r.video_id)

    def _error(self, mensaje: str):
        self.boton.setEnabled(True)
        self.estado.setText("")
        QMessageBox.critical(self, "Error de búsqueda", mensaje)
