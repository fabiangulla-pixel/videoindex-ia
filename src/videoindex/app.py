"""Punto de entrada de la GUI de VideoIndex IA."""

from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    # Lección E0 en esta máquina: el backend ffmpeg de Qt Multimedia crashea
    # al renderizar video en QVideoWidget; el backend nativo WMF funciona.
    if sys.platform == "win32":
        os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

    from PySide6.QtWidgets import QApplication

    from videoindex.config.settings import (
        cargar_preferencias_rag,
        cargar_preferencias_transcripcion,
    )
    from videoindex.presentation.main_window import MainWindow

    cargar_preferencias_rag()
    cargar_preferencias_transcripcion()

    app = QApplication(sys.argv)
    app.setApplicationName("VideoIndex IA")
    ventana = MainWindow()

    try:
        from videoindex.presentation.ask_view import AskView

        ventana.agregar_pestana_rag(AskView(abrir_video=ventana.player.abrir_en))
    except ImportError:
        pass  # E5 aún no desplegada

    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
