"""Diálogo de recorte: ver el video y marcar inicio/fin antes de transcribir.

Mini-reproductor propio (no reutiliza PlayerWidget: aquí no aplican notas ni
salto a contenido — solo navegar y marcar). El recorte físico ocurre después,
en TrimWorker; este diálogo solo captura (inicio_s, fin_s)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from videoindex.presentation.workers import DetectarInicioWorker


def _fmt(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class TrimDialog(QDialog):
    def __init__(self, ruta_video: str, titulo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"✂ Recortar — {titulo}")
        self.setMinimumSize(640, 480)
        self._ruta = ruta_video
        self._inicio_ms = 0
        self._fin_ms: int | None = None  # None = hasta el final

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.video = QVideoWidget(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)

        self.boton_play = QPushButton("▶")
        self.boton_play.setFixedWidth(44)
        self.boton_play.clicked.connect(self._toggle)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.tiempo = QLabel("00:00:00 / 00:00:00")
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_duracion)

        transporte = QHBoxLayout()
        transporte.addWidget(self.boton_play)
        transporte.addWidget(self.slider, stretch=1)
        transporte.addWidget(self.tiempo)

        self.boton_marcar_inicio = QPushButton("⬇ Marcar INICIO aquí")
        self.boton_marcar_inicio.clicked.connect(self._marcar_inicio)
        self.boton_marcar_fin = QPushButton("⬇ Marcar FIN aquí")
        self.boton_marcar_fin.clicked.connect(self._marcar_fin)
        marcas = QHBoxLayout()
        marcas.addWidget(self.boton_marcar_inicio)
        marcas.addWidget(self.boton_marcar_fin)

        self.etiqueta_marcas = QLabel()
        self._refrescar_marcas()

        nota = QLabel(
            "El recorte se guarda como archivo NUEVO (el original en disco no se toca) "
            "y reemplaza al original en la biblioteca. El corte de inicio cae en el "
            "keyframe más cercano: precisión de ±unos segundos."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: gray; font-size: 11px;")

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("✂ Recortar")
        botones.accepted.connect(self._validar_y_aceptar)
        botones.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.video, stretch=1)
        layout.addLayout(transporte)
        layout.addLayout(marcas)
        layout.addWidget(self.etiqueta_marcas)
        layout.addWidget(nota)
        layout.addWidget(botones)

        self.player.setSource(QUrl.fromLocalFile(ruta_video))

        # Sugerencia asíncrona: si el video empieza con pantalla negra, la
        # marca de inicio se pre-llena sola (el usuario puede cambiarla).
        self._detector = DetectarInicioWorker(ruta_video)
        self._detector.listo.connect(self._sugerir_inicio)
        self._detector.start()

    def rango_seleccionado(self) -> tuple[float, float | None]:
        """(inicio_s, fin_s) — fin_s None significa 'hasta el final'."""
        fin_s = self._fin_ms / 1000 if self._fin_ms is not None else None
        return self._inicio_ms / 1000, fin_s

    def _sugerir_inicio(self, offset_s: float) -> None:
        # Solo si el usuario no marcó nada todavía: su elección manda.
        if offset_s > 0 and self._inicio_ms == 0:
            self._inicio_ms = int(offset_s * 1000)
            self._refrescar_marcas(sugerido=True)

    def _marcar_inicio(self) -> None:
        self._inicio_ms = self.player.position()
        self._refrescar_marcas()

    def _marcar_fin(self) -> None:
        self._fin_ms = self.player.position()
        self._refrescar_marcas()

    def _refrescar_marcas(self, sugerido: bool = False) -> None:
        fin = _fmt(self._fin_ms) if self._fin_ms is not None else "final del video"
        extra = "  (inicio detectado automáticamente)" if sugerido else ""
        self.etiqueta_marcas.setText(f"Recorte: {_fmt(self._inicio_ms)}  →  {fin}{extra}")

    def _validar_y_aceptar(self) -> None:
        if self._fin_ms is not None and self._fin_ms <= self._inicio_ms:
            QMessageBox.warning(
                self, "Rango inválido", "La marca de FIN debe ir después de la de INICIO."
            )
            return
        if self._inicio_ms == 0 and self._fin_ms is None:
            QMessageBox.information(
                self, "Nada que recortar", "No marcaste inicio ni fin: el video quedaría igual."
            )
            return
        self.accept()

    def _toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.boton_play.setText("▶")
        else:
            self.player.play()
            self.boton_play.setText("⏸")

    def _on_pos(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.tiempo.setText(f"{_fmt(pos)} / {_fmt(self.player.duration())}")

    def _on_duracion(self, d: int) -> None:
        self.slider.setRange(0, d)

    def done(self, resultado: int) -> None:
        # Soltar el archivo y el hilo detector antes de cerrar: el TrimWorker
        # va a leer este mismo archivo, y destruir un QThread vivo crashea.
        self.player.stop()
        self.player.setSource(QUrl())
        if self._detector.isRunning():
            self._detector.wait(3000)
        super().done(resultado)
