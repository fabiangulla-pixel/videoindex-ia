"""Une un video sin audio con su audio en un solo archivo, sin recodificar.

Caso real: al bajar de YouTube con un descargador que separa las pistas, el
usuario acaba con un .mp4 que solo tiene imagen. Para transcribir hace falta
el sonido, y para identificar hablantes por los rótulos hace falta la imagen:
en un archivo suelto nunca están las dos cosas.

Remux (copia de paquetes), no recodificación: es cuestión de segundos y no
pierde calidad. Mismo enfoque que infrastructure/media/trimmer.py.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

VIDEO = Path(r"D:\Chile\workeo\video\videoplayback.mp4")
AUDIO = next(Path(r"D:\Chile\workeo\transcripcion_work").glob("*.m4a"))
DESTINO = Path(r"D:\Chile\workeo\Estravagario - documental completo.mp4")


def unir(ruta_video: Path, ruta_audio: Path, destino: Path) -> Path:
    import av

    inicio = time.time()
    with (
        av.open(str(ruta_video)) as cont_video,
        av.open(str(ruta_audio)) as cont_audio,
        av.open(str(destino), "w") as salida,
    ):
        entrada_v = cont_video.streams.video[0]
        entrada_a = cont_audio.streams.audio[0]
        salida_v = salida.add_stream_from_template(entrada_v)
        salida_a = salida.add_stream_from_template(entrada_a)

        for paquete in cont_video.demux(entrada_v):
            if paquete.dts is None:
                continue
            paquete.stream = salida_v
            salida.mux(paquete)
        for paquete in cont_audio.demux(entrada_a):
            if paquete.dts is None:
                continue
            paquete.stream = salida_a
            salida.mux(paquete)

    print(f"Unido en {time.time() - inicio:.1f}s -> {destino}")
    return destino


if __name__ == "__main__":
    from videoindex.infrastructure.media.probe import duracion_segundos

    unir(VIDEO, AUDIO, DESTINO)
    import av

    with av.open(str(DESTINO)) as c:
        print(f"streams: {len(c.streams.video)} video, {len(c.streams.audio)} audio")
        print(f"duración: {(duracion_segundos(DESTINO) or 0) / 60:.1f} min")
        print(f"tamaño: {DESTINO.stat().st_size / 1e6:.0f} MB")
