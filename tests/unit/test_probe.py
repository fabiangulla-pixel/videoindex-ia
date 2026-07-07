"""Detección de negro/silencio inicial (luminancia de video) — sin decodificar
video real: la lógica de umbral se testea con arrays numpy sintéticos."""

import numpy as np

from videoindex.infrastructure.media.probe import _es_frame_claro, detectar_inicio_contenido


def test_frame_negro_no_supera_umbral():
    negro = np.zeros((10, 10), dtype=np.uint8)
    assert not _es_frame_claro(float(np.mean(negro)), umbral=16.0)


def test_frame_claro_supera_umbral():
    claro = np.full((10, 10), 200, dtype=np.uint8)
    assert _es_frame_claro(float(np.mean(claro)), umbral=16.0)


def test_frame_justo_en_el_umbral_no_es_claro():
    # comparación estricta (>): igual al umbral no cuenta como claro
    assert not _es_frame_claro(16.0, umbral=16.0)


def test_archivo_inexistente_devuelve_cero_sin_lanzar():
    assert detectar_inicio_contenido("C:/ruta/que/no/existe.mp4") == 0.0


def test_archivo_de_audio_puro_devuelve_cero(tmp_path):
    # Un .wav válido pero sin stream de video: la rama "sin stream de video"
    # debe devolver 0.0 sin intentar decodificar frames.
    import wave

    ruta = tmp_path / "solo_audio.wav"
    with wave.open(str(ruta), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)
    assert detectar_inicio_contenido(str(ruta)) == 0.0
