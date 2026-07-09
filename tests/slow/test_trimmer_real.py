"""Valida el recorte REAL por remux con PyAV (marcado slow).

Genera un mp4 sintético y verifica que recortar_video produce un archivo
nuevo con la duración esperada SIN tocar el original."""

from fractions import Fraction

import pytest

from videoindex.infrastructure.media.probe import duracion_segundos
from videoindex.infrastructure.media.trimmer import recortar_video

pytestmark = pytest.mark.slow


def _generar_mp4(destino, segundos=6, fps=10):
    import av
    import numpy as np

    with av.open(str(destino), "w") as out:
        stream = out.add_stream("h264", rate=fps)
        stream.width, stream.height = 320, 240
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, fps)
        # gop pequeño = keyframes frecuentes → cortes precisos en el test
        stream.codec_context.gop_size = fps
        for i in range(segundos * fps):
            img = np.full((240, 320, 3), (i * 3) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            for paquete in stream.encode(frame):
                out.mux(paquete)
        for paquete in stream.encode():
            out.mux(paquete)


def test_recorta_inicio_y_fin(tmp_path):
    origen = tmp_path / "original.mp4"
    _generar_mp4(origen, segundos=6)
    bytes_original = origen.read_bytes()

    destino = tmp_path / "recortado.mp4"
    resultado = recortar_video(origen, destino, inicio_s=2.0, fin_s=4.0)

    assert resultado == destino
    assert destino.exists()
    dur = duracion_segundos(destino)
    # el corte cae en keyframes (cada 1s en este mp4): 2s pedidos ± margen
    assert dur is not None and 1.5 <= dur <= 3.5
    assert origen.read_bytes() == bytes_original  # el original no se tocó


def test_recorta_solo_inicio_hasta_el_final(tmp_path):
    origen = tmp_path / "original.mp4"
    _generar_mp4(origen, segundos=6)

    destino = tmp_path / "recortado.mp4"
    recortar_video(origen, destino, inicio_s=3.0, fin_s=None)

    dur = duracion_segundos(destino)
    assert dur is not None and 2.0 <= dur <= 4.0  # ~3s restantes ± keyframe


def test_reporta_progreso_creciente(tmp_path):
    origen = tmp_path / "original.mp4"
    _generar_mp4(origen, segundos=4)

    fracciones: list[float] = []
    recortar_video(origen, tmp_path / "r.mp4", 0.0, 4.0, progreso=fracciones.append)

    assert fracciones
    assert all(0.0 <= f <= 1.0 for f in fracciones)
    assert fracciones == sorted(fracciones)  # monótono creciente


def test_rango_invalido_lanza(tmp_path):
    origen = tmp_path / "original.mp4"
    _generar_mp4(origen, segundos=2)

    with pytest.raises(ValueError):
        recortar_video(origen, tmp_path / "r.mp4", inicio_s=3.0, fin_s=1.0)
