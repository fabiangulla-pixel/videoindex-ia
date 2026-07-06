"""Diagnóstico mínimo: QMediaPlayer SIN QVideoWidget (¿el crash es del render?)."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication

ruta = sys.argv[1]
app = QApplication(sys.argv)
player = QMediaPlayer()
audio = QAudioOutput()
player.setAudioOutput(audio)


def on_status(status):
    print(f"status={status}", flush=True)
    if status == QMediaPlayer.MediaStatus.LoadedMedia:
        player.play()
        player.setPosition(1500)
        QTimer.singleShot(800, verificar)


def verificar():
    print(f"duración={player.duration()} ms, posición={player.position()} ms", flush=True)
    ok = player.duration() > 0 and player.position() >= 1000
    print("OK sin widget" if ok else "FALLO sin widget", flush=True)
    os._exit(0 if ok else 1)


player.mediaStatusChanged.connect(on_status)
player.errorOccurred.connect(lambda e, m: print(f"error={m}", flush=True))
player.setSource(QUrl.fromLocalFile(ruta))
QTimer.singleShot(10000, lambda: os._exit(2))
app.exec()
