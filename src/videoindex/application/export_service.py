"""Exportación del corpus a JSON: el conocimiento extraído de cada video
(chunks con timestamps, entidades, anotaciones manuales) en un formato
abierto y reutilizable fuera de la app (otro RAG, un GPT, análisis propio).

Un JSON por video — mismo espíritu que el corpus USICAMM del usuario
(PDF→MD+JSONL): el corpus es un ENTREGABLE, no un detalle interno."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from videoindex.infrastructure.db.repositories import (
    AnnotationRepo,
    ChunkRepo,
    EntityRepo,
    ProjectRepo,
    VideoRepo,
)


def corpus_de_video(con: sqlite3.Connection, video_id: str) -> dict:
    """Todo lo extraído de un video, como dict serializable a JSON.
    Lanza ValueError si el video no existe."""
    video = VideoRepo(con).por_id(video_id)
    if video is None:
        raise ValueError(f"Video no encontrado: {video_id}")

    nombres_proyecto = {p.project_id: p.name for p in ProjectRepo(con).listar()}
    entidades, chunks_por_entidad = EntityRepo(con).catalogo_de_video(video_id)
    entidades_por_chunk: dict[str, list[dict]] = {}
    for eid, chunk_ids in chunks_por_entidad.items():
        ent = entidades[eid]
        for cid in chunk_ids:
            entidades_por_chunk.setdefault(cid, []).append(
                {"label": ent.label, "tipo": ent.entity_type}
            )

    return {
        "video": {
            "video_id": video.video_id,
            "titulo": video.title,
            "archivo": video.path,
            "checksum_sha256": video.checksum,
            "duracion_s": video.duration_seconds,
            "proyecto": nombres_proyecto.get(video.project_id),
            "curso": video.course_name,
            "estado": video.processing_status,
            "inicio_contenido_s": video.content_start_s,
        },
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "inicio_s": c.start_time,
                "fin_s": c.end_time,
                "texto": c.full_text,
                "tipo_discurso": c.discourse_type,
                "confianza": c.avg_confidence,
                "entidades": entidades_por_chunk.get(c.chunk_id, []),
            }
            for c in ChunkRepo(con).por_video(video_id)
        ],
        "anotaciones_manuales": [
            {"timestamp_s": a.timestamp_s, "texto": a.text}
            for a in AnnotationRepo(con).por_video(video_id)
        ],
        "exportado_el": datetime.now(UTC).isoformat(),
    }


def exportar_video_json(con: sqlite3.Connection, video_id: str, destino: str | Path) -> Path:
    destino = Path(destino)
    destino.write_text(
        json.dumps(corpus_de_video(con, video_id), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destino


def exportar_proyecto_json(
    con: sqlite3.Connection, project_id: str | None, carpeta: str | Path
) -> list[Path]:
    """Un JSON por video COMPLETADO del proyecto (mismo sentinel que
    VideoRepo.listar: '__todos__' exporta toda la biblioteca, None los
    videos sin proyecto). Los no completados se omiten: aún no tienen
    corpus que exportar. Devuelve las rutas escritas."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []
    for video in VideoRepo(con).listar(project_id):
        if video.processing_status != "completed":
            continue
        nombre_seguro = "".join(c if c.isalnum() or c in " _-." else "_" for c in video.title)
        escritos.append(exportar_video_json(con, video.video_id, carpeta / f"{nombre_seguro}.json"))
    return escritos
