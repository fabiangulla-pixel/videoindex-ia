"""Smoke test E0: ¿QMediaPlayer reproduce mp4 y salta a timestamp en esta máquina?

Genera un mp4 sintético con PyAV (sin ffmpeg externo), lo carga en QMediaPlayer
y hace setPosition(). Sale con 0 si todo funciona; imprime el diagnóstico.

Uso:  python scripts/smoke_player.py [ruta_mp4_opcional]
"""

from __future__ import annotations

import sys
import tempfile
from fractions import Fraction
from pathlib import Path


def generar_mp4(destino: Path, segundos: int = 3) -> None:
    import av
    import numpy as np

    with av.open(str(destino), "w") as out:
        stream = out.add_stream("h264", rate=10)
        stream.width, stream.height = 320, 240
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 10)
        for i in range(segundos * 10):
            img = np.zeros((240, 320, 3), dtype=np.uint8)
            img[:, :, i % 3] = (i * 8) % 255  # color cambiante
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            for paquete in stream.encode(frame):
                out.mux(paquete)
        for paquete in stream.encode():
            out.mux(paquete)


def main() -> int:
    if len(sys.argv) > 1:
        ruta = Path(sys.argv[1])
    else:
        ruta = Path(tempfile.gettempdir()) / "videoindex_smoke.mp4"
        print(f"Generando mp4 sintético: {ruta}")
        generar_mp4(ruta)

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    player = QMediaPlayer()
    audio = QAudioOutput()
    video = QVideoWidget()
    player.setAudioOutput(audio)
    player.setVideoOutput(video)

    estado = {"ok": False, "error": ""}

    def on_status(status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            player.play()
            # el seek va DESPUÉS de que la reproducción arranca, si no WMF lo pisa
            QTimer.singleShot(300, lambda: player.setPosition(1500))
            QTimer.singleShot(900, verificar)

    def on_error(_err, msg):
        estado["error"] = msg
        app.quit()

    def verificar():
        pos = player.position()
        dur = player.duration()
        estado["ok"] = dur > 0 and pos >= 1000
        print(f"duración={dur} ms, posición tras salto={pos} ms", flush=True)
        player.stop()
        player.setVideoOutput(None)
        app.quit()

    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(on_error)
    video.resize(320, 240)
    video.show()
    player.setSource(QUrl.fromLocalFile(str(ruta)))
    QTimer.singleShot(10000, app.quit)  # red de seguridad
    app.exec()

    if estado["ok"]:
        print("SMOKE OK: QMediaPlayer reproduce mp4 y salta a timestamp.", flush=True)
        # os._exit evita crashes de teardown de Qt Multimedia al salir.
        import os

        os._exit(0)
    print(f"SMOKE FALLO: {estado['error'] or 'sin diagnóstico'} (plan B: instalar K-Lite)", flush=True)
    import os

    os._exit(1)


if __name__ == "__main__":
    sys.exit(main())
