"""Metadatos del video vía PyAV (llega como dependencia de faster-whisper)."""

from __future__ import annotations

import hashlib
from pathlib import Path

EXTENSIONES_VIDEO = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v", ".mp3", ".m4a", ".wav"}


def duracion_segundos(ruta: str | Path) -> float | None:
    try:
        import av

        with av.open(str(ruta)) as contenedor:
            if contenedor.duration is None:
                return None
            return contenedor.duration / av.time_base
    except Exception:
        return None


def checksum_sha256(ruta: str | Path, bloque: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


def es_video(ruta: Path) -> bool:
    return ruta.suffix.lower() in EXTENSIONES_VIDEO


def _es_frame_claro(promedio_luminancia: float, umbral: float) -> bool:
    """Extraída de detectar_inicio_contenido() para ser testeable con
    arrays numpy sintéticos, sin decodificar video real."""
    return promedio_luminancia > umbral


def detectar_inicio_contenido(
    ruta: str | Path,
    umbral_luminancia: float = 16.0,
    paso_muestreo_s: float = 1.0,
    limite_busqueda_s: float = 120.0,
) -> float:
    """Primer instante (s) donde un frame de video deja de ser "negro"
    (luminancia promedio por encima del umbral). Análisis de VIDEO,
    independiente del VAD de audio de Whisper (que solo filtra silencio,
    no negro con ruido de fondo).

    Puramente informativo para la UI de reproducción: el valor devuelto
    NUNCA se resta de los timestamps de transcripción, que siguen
    absolutos respecto al archivo original (ADR-002).

    Comportamiento seguro por defecto — nunca lanza excepción, devuelve
    0.0 (equivalente a "sin offset detectado") si: el archivo no tiene
    stream de video (audio puro), PyAV falla al abrir/decodificar, o
    nunca se encuentra un frame por encima del umbral dentro de
    `limite_busqueda_s` (video muy oscuro o más corto que el límite).
    """
    try:
        import av
        import numpy as np

        with av.open(str(ruta)) as contenedor:
            if not contenedor.streams.video:
                return 0.0
            stream = contenedor.streams.video[0]
            siguiente_muestra = 0.0
            for frame in contenedor.decode(stream):
                if frame.pts is None:
                    continue
                t = float(frame.pts * frame.time_base)
                if t < siguiente_muestra:
                    continue
                if t > limite_busqueda_s:
                    break
                gris = frame.to_ndarray(format="gray8")
                if _es_frame_claro(float(np.mean(gris)), umbral_luminancia):
                    return t
                siguiente_muestra += paso_muestreo_s
            return 0.0
    except Exception:
        return 0.0
