"""Recorte previo a transcripción: orquesta el reemplazo en biblioteca.

El recorte físico lo hace infrastructure/media/trimmer.py (remux sin
re-codificar, archivo nuevo). Aquí vive la parte de datos: el video
recortado entra a la biblioteca como video propio (checksum nuevo, estado
'pending') heredando proyecto/curso del original, y el original SALE de la
biblioteca para no transcribir dos veces lo mismo — su archivo en disco no
se toca nunca."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from videoindex.domain.models import Video
from videoindex.infrastructure.db.repositories import VideoRepo
from videoindex.infrastructure.media.probe import checksum_sha256, duracion_segundos


def generar_ruta_recorte(origen: str | Path) -> Path:
    """`clase.mp4` → `clase_recortado.mp4` junto al original; si ya existe,
    sufijo numerado (`clase_recortado_2.mp4`, …) para no pisar recortes
    anteriores."""
    origen = Path(origen)
    candidata = origen.with_name(f"{origen.stem}_recortado{origen.suffix}")
    n = 2
    while candidata.exists():
        candidata = origen.with_name(f"{origen.stem}_recortado_{n}{origen.suffix}")
        n += 1
    return candidata


def registrar_recorte(
    con: sqlite3.Connection, original: Video, ruta_recortada: str | Path
) -> Video:
    """Alta del video recortado en la biblioteca, heredando proyecto y curso
    del original. NO elimina el original — eso lo decide el llamador (el
    worker usa VideoDeletionService, que también limpia derivados si los
    hubiera)."""
    ruta_recortada = Path(ruta_recortada)
    nuevo = Video(
        video_id=str(uuid4()),
        title=ruta_recortada.stem,
        path=str(ruta_recortada),
        checksum=checksum_sha256(ruta_recortada),
        duration_seconds=duracion_segundos(ruta_recortada),
        course_name=original.course_name,
        session_name=ruta_recortada.stem,
        project_id=original.project_id,
    )
    VideoRepo(con).guardar(nuevo)
    return nuevo
