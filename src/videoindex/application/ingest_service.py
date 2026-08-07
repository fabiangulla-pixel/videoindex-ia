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
from videoindex.infrastructure.media.youtube import MediaDescargado


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
            self._registrar(archivo, resultado, course_name, project_id)
        return resultado

    def registrar_descarga(
        self,
        media: MediaDescargado,
        course_name: str | None = None,
        project_id: str | None = None,
    ) -> ResultadoIngesta:
        """Alta de un archivo recién bajado de una URL.

        Misma identidad por checksum que el escaneo de carpeta: bajar dos
        veces el mismo video no lo duplica en la biblioteca (y si ya estaba
        como archivo local, se le añade la procedencia sin re-transcribir).
        """
        resultado = ResultadoIngesta()
        self._registrar(
            media.ruta,
            resultado,
            course_name,
            project_id,
            titulo=media.titulo,
            source_url=media.url,
            source_channel=media.canal,
            source_published_at=media.fecha_publicacion,
        )
        return resultado

    def _registrar(
        self,
        archivo: Path,
        resultado: ResultadoIngesta,
        course_name: str | None,
        project_id: str | None,
        titulo: str | None = None,
        source_url: str | None = None,
        source_channel: str | None = None,
        source_published_at: str | None = None,
    ) -> None:
        """Alta idempotente de UN archivo, compartida por el escaneo de
        carpeta y la descarga por URL."""
        checksum = checksum_sha256(archivo)
        existente = self.videos.por_checksum(checksum)
        if existente:
            cambio = str(archivo) != existente.path
            if cambio:
                existente.path = str(archivo)
            # La procedencia se completa si llega ahora y no estaba (el
            # UPSERT del repo usa COALESCE: nunca borra la que ya había).
            if source_url and not existente.source_url:
                existente.source_url = source_url
                existente.source_channel = source_channel
                existente.source_published_at = source_published_at
                cambio = True
            if cambio:
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
            return

        nombre = titulo or archivo.stem
        video = Video(
            video_id=str(uuid4()),
            title=nombre,
            path=str(archivo),
            checksum=checksum,
            duration_seconds=duracion_segundos(archivo),
            course_name=course_name,
            session_name=nombre,
            project_id=project_id,
            source_url=source_url,
            source_channel=source_channel,
            source_published_at=source_published_at,
        )
        self.videos.guardar(video)
        resultado.nuevos.append(video)
