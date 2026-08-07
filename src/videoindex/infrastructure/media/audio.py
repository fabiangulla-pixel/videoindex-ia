"""Decodificación de audio a PCM mono con PyAV — sin ffmpeg en el PATH.

Lo usa la diarización, que necesita la forma de onda cruda (Whisper decodifica
por su cuenta dentro de faster-whisper y no expone lo que decodificó).

El audio se devuelve en int16, no en float32: una grabación de 2 h a 16 kHz
son 230 MB en int16 y el doble en float32, y a la red neuronal solo se le
pasa un tramo cada vez (`tramo()` convierte ese tramo, no el archivo entero).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000  # el que esperan los modelos de voz (ECAPA, Whisper)


def cargar_audio_mono(ruta: str | Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Pista de audio completa como int16 mono al sample rate pedido.

    Lanza ValueError si el archivo no tiene audio (un mp4 mudo): sin audio no
    hay nada que diarizar y quien llama debe poder distinguir ese caso de un
    fallo del modelo.
    """
    import av

    with av.open(str(ruta)) as contenedor:
        if not contenedor.streams.audio:
            raise ValueError(f"El archivo no tiene pista de audio: {ruta}")
        stream = contenedor.streams.audio[0]
        remuestreador = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        trozos: list[np.ndarray] = []
        for frame in contenedor.decode(stream):
            for remuestreado in remuestreador.resample(frame):
                trozos.append(remuestreado.to_ndarray().reshape(-1))
        # Flush: el remuestreador puede tener muestras retenidas en su buffer
        # interno; sin esto se pierde la cola del audio.
        for remuestreado in remuestreador.resample(None):
            trozos.append(remuestreado.to_ndarray().reshape(-1))

    if not trozos:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(trozos).astype(np.int16)


def tramo(
    audio: np.ndarray, inicio_s: float, fin_s: float, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """Trozo [inicio, fin) como float32 en [-1, 1], recortado a los límites
    reales del audio (los timestamps de Whisper pueden excederlos por
    milésimas al final del archivo)."""
    i = max(0, int(inicio_s * sample_rate))
    j = min(len(audio), int(fin_s * sample_rate))
    if j <= i:
        return np.zeros(0, dtype=np.float32)
    return audio[i:j].astype(np.float32) / 32768.0
