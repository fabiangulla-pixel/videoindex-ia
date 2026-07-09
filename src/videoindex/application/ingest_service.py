"""Ingesta de videos: registrar, validar, calcular checksum — idempotente.

Idempotencia (SAD §3.4): el checksum sha256 es la identidad del video.
- checksum ya registrado y 'completed' → skip.
- checksum registrado con otra ruta → se actualiza la ruta (archivo movido).
- checksum nuevo → alta con status 'pending'.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from videoindex.domain.models import Video
from videoindex.infrastructure.db.repositories import VideoRepo
from videoindex.infrastructure.media.probe import checksum_sha256, duracion_segundos, es_video


@dataclass
class ResultadoIngesta:
    nuevos: list[Video] = field(default_factory=list)
    ya_completados: list[Video] = field(default_factory=list)
    pendientes_previos: list[Video] = field(default_factory=list)

    @property
    def por_procesar(self) -> list[Video]:
        return self.nuevos + self.pendientes_previos

    @property
    def horas_totales(self) -> float:
        total = sum(v.duration_seconds or 0.0 for v in self.por_procesar)
        return total / 3600


class IngestService:
    def __init__(self, con: sqlite3.Connection):
        self.videos = VideoRepo(con)

    def escanear_carpeta(
        self,
        carpeta: str | Path,
        course_name: str | None = None,
        progreso: Callable[[int, int, str], None] | None = None,
        project_id: str | None = None,
    ) -> ResultadoIngesta:
        """progreso(indice_1based, total, nombre_archivo) — para mostrar avance
        durante el cálculo de checksum, que puede tardar en archivos grandes
        o en red (p. ej. Google Drive sin caché local)."""
        carpeta = Path(carpeta)
        if not carpeta.is_dir():
            raise NotADirectoryError(f"No es una carpeta: {carpeta}")

        resultado = ResultadoIngesta()
        archivos = sorted(p for p in carpeta.rglob("*") if p.is_file() and es_video(p))
        for i, archivo in enumerate(archivos, 1):
            if progreso:
                progreso(i, len(archivos), archivo.name)
            checksum = checksum_sha256(archivo)
            existente = self.videos.por_checksum(checksum)
            if existente:
                if str(archivo) != existente.path:
                    existente.path = str(archivo)
                    self.videos.guardar(existente)
                # Un video ya conocido pero SIN proyecto se adopta al proyecto
                # bajo el que se está escaneando (caso real: mismos archivos
                # copiados a otro disco, re-escaneados dentro de un proyecto
                # nuevo — sin esto quedaban invisibles bajo el filtro del
                # proyecto). Si ya pertenece a OTRO proyecto, se respeta.
                if project_id is not None and existente.project_id is None:
                    existente.project_id = project_id
                    self.videos.asignar_proyecto(existente.video_id, project_id)
                if existente.processing_status == "completed":
                    resultado.ya_completados.append(existente)
                else:
                    resultado.pendientes_previos.append(existente)
                continue

            video = Video(
                video_id=str(uuid4()),
                title=archivo.stem,
                path=str(archivo),
                checksum=checksum,
                duration_seconds=duracion_segundos(archivo),
                course_name=course_name,
                session_name=archivo.stem,
                project_id=project_id,
            )
            self.videos.guardar(video)
            resultado.nuevos.append(video)
        return resultado
