"""Valida la integración REAL faster-whisper/PyAV en este Python (marcado slow).

Corre con:  pytest -m slow
Descarga el modelo `tiny` (~75 MB) la primera vez.
"""

import math
import wave

import pytest

pytestmark = pytest.mark.slow


def _wav_sintetico(ruta, segundos=6, freq=440):
    """Tono senoidal — whisper no transcribirá palabras, pero el pipeline de
    decodificación, VAD y timestamps debe funcionar sin explotar."""
    rate = 16000
    with wave.open(str(ruta), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        datos = bytearray()
        for i in range(rate * segundos):
            v = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            datos += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(datos))


def test_whisper_decodifica_y_da_timestamps_absolutos(tmp_path):
    from videoindex.infrastructure.transcription.faster_whisper_provider import (
        FasterWhisperProvider,
    )

    ruta = tmp_path / "tono.wav"
    _wav_sintetico(ruta)
    provider = FasterWhisperProvider(modelo="tiny", idioma="es", compute_type="int8")
    # Un tono puro puede no producir segmentos (VAD los filtra): lo que se
    # valida es que la integración no falla y que si hay segmentos, sus
    # timestamps son absolutos dentro del rango del archivo.
    segmentos = provider.transcribir(str(ruta), "video-test")
    for s in segmentos:
        assert 0.0 <= s.start_time <= s.end_time <= 7.0
        assert s.video_id == "video-test"
        assert 0.0 <= s.confidence <= 1.0
