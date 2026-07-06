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
