"""Reproductor con salto a timestamp — Video Navigation Engine del SAD.

Lección del smoke test E0 (esta máquina, Win10): con el backend ffmpeg de Qt
el render de QVideoWidget crashea; con QT_MEDIA_BACKEND=windows (WMF) funciona.
app.py fija esa variable ANTES de crear la QApplication. Además, el seek debe
hacerse DESPUÉS de que play() arranca, o WMF lo pisa.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_COLCHON_MS = 2000  # abre 2 s antes del timestamp pedido (margen de la spec)


def _fmt(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class PlayerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.video = QVideoWidget(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)

        self.titulo = QLabel("Sin video")
        self.titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.boton_play = QPushButton("⏸")
        self.boton_play.setFixedWidth(44)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.tiempo = QLabel("00:00:00 / 00:00:00")

        controles = QHBoxLayout()
        controles.addWidget(self.boton_play)
        controles.addWidget(self.slider, stretch=1)
        controles.addWidget(self.tiempo)

        layout = QVBoxLayout(self)
        layout.addWidget(self.titulo)
        layout.addWidget(self.video, stretch=1)
        layout.addLayout(controles)

        self.boton_play.clicked.connect(self._toggle)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))

        self._ruta_actual: str | None = None

    def abrir_en(self, ruta: str, titulo: str, start_time_s: float) -> None:
        """Abre el video y salta al instante exacto (menos el colchón)."""
        destino_ms = max(0, int(start_time_s * 1000) - _COLCHON_MS)
        self.titulo.setText(titulo)
        if self._ruta_actual != ruta:
            self._ruta_actual = ruta
            self.player.setSource(QUrl.fromLocalFile(ruta))
        self.player.play()
        # WMF: el seek va después de que la reproducción arranca (lección E0)
        QTimer.singleShot(300, lambda: self.player.setPosition(destino_ms))
        self.boton_play.setText("⏸")

    def _toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.boton_play.setText("▶")
        else:
            self.player.play()
            self.boton_play.setText("⏸")

    def _on_pos(self, pos: int):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.tiempo.setText(f"{_fmt(pos)} / {_fmt(self.player.duration())}")
