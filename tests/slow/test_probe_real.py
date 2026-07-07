"""Valida la detección REAL de negro/silencio inicial con PyAV (marcado slow).

Genera un mp4 sintético: N segundos de negro seguidos de frames claros, y
verifica que detectar_inicio_contenido() encuentra el cambio.
"""

from fractions import Fraction

import pytest

from videoindex.infrastructure.media.probe import detectar_inicio_contenido

pytestmark = pytest.mark.slow


def _generar_mp4_negro_luego_claro(destino, segundos_negro=3, segundos_claro=2, fps=10):
    import av
    import numpy as np

    with av.open(str(destino), "w") as out:
        stream = out.add_stream("h264", rate=fps)
        stream.width, stream.height = 320, 240
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, fps)
        for _i in range(segundos_negro * fps):
            img = np.zeros((240, 320, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            for paquete in stream.encode(frame):
                out.mux(paquete)
        for _i in range(segundos_claro * fps):
            img = np.full((240, 320, 3), 220, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            for paquete in stream.encode(frame):
                out.mux(paquete)
        for paquete in stream.encode():
            out.mux(paquete)


def test_detecta_transicion_de_negro_a_claro(tmp_path):
    ruta = tmp_path / "negro_luego_claro.mp4"
    _generar_mp4_negro_luego_claro(ruta, segundos_negro=3, segundos_claro=2)

    offset = detectar_inicio_contenido(str(ruta), paso_muestreo_s=0.5)
    # el cambio ocurre a los 3s; con muestreo cada 0.5s se espera cerca de ahí
    assert 2.5 <= offset <= 3.5


def test_video_totalmente_negro_devuelve_cero(tmp_path):
    ruta = tmp_path / "todo_negro.mp4"
    _generar_mp4_negro_luego_claro(ruta, segundos_negro=2, segundos_claro=0)

    offset = detectar_inicio_contenido(str(ruta), limite_busqueda_s=5.0)
    assert offset == 0.0
