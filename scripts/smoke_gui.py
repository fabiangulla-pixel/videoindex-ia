"""Smoke: la GUI completa se construye y las 3 pestañas existen. Sale sola."""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # sin ventana real
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")
# BD desechable, por dos razones: no tocar la biblioteca real del usuario y,
# sobre todo, no colgar el smoke. Con la BD real, MainWindow abre al arrancar
# un QMessageBox modal si hay videos a medio procesar ("¿continuar?") y
# offscreen nadie puede cerrarlo: el script se queda esperando para siempre.
os.environ.setdefault("VIDEOINDEX_DATA", tempfile.mkdtemp(prefix="videoindex_smoke_"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from videoindex.presentation.ask_view import AskView
from videoindex.presentation.main_window import MainWindow

app = QApplication(sys.argv)
ventana = MainWindow()
ventana.agregar_pestana_rag(AskView(abrir_video=ventana.player.abrir_en))

# La consola de Windows es cp1252 y los nombres de las pestañas llevan
# emojis: sin esto, imprimirlos revienta el smoke con UnicodeEncodeError.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
nombres = [ventana.tabs.tabText(i) for i in range(ventana.tabs.count())]
print("Pestañas:", nombres, flush=True)
ok = ventana.tabs.count() == 3

QTimer.singleShot(200, app.quit)
app.exec()
print("SMOKE GUI OK" if ok else "SMOKE GUI FALLO", flush=True)
os._exit(0 if ok else 1)
