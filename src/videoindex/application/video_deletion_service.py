"""Eliminar un video de la biblioteca: limpia todo lo derivado (transcripción,
chunks, entidades, embeddings/FAISS, anotaciones) sin tocar el archivo en
disco. El archivo original NUNCA se borra desde aquí — es una acción aparte,
explícita, que decide la GUI."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from videoindex.infrastructure.db.repositories import (
    AnnotationRepo,
    ChunkRepo,
    EmbeddingRepo,
    EntityRepo,
    SegmentRepo,
    VideoRepo,
)

if TYPE_CHECKING:
    from videoindex.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider
    from videoindex.infrastructure.vector.faiss_index import FaissIndex


class VideoDeletionService:
    """embedder/faiss_index: los mismos ya cacheados en ServiciosCache
    (instanciarlos de nuevo aquí recargaría el modelo de embeddings).
    Pueden ser None SOLO si el video no tiene chunks indexados (pending/
    failed temprano): permite el borrado ligero sin cargar modelos."""

    def __init__(
        self,
        con: sqlite3.Connection,
        embedder: LocalEmbeddingProvider | None,
        faiss_index: FaissIndex | None,
    ):
        self.con = con
        self.videos = VideoRepo(con)
        self.segments = SegmentRepo(con)
        self.chunks = ChunkRepo(con)
        self.entities = EntityRepo(con)
        self.embeddings = EmbeddingRepo(con)
        self.annotations = AnnotationRepo(con)
        self.embedder = embedder
        self.faiss_index = faiss_index

    def eliminar(self, video_id: str) -> None:
        """Orden: primero limpiar el índice FAISS (necesita los faiss_ids
        ANTES de borrar los mapeos), luego las tablas SQL en cascada manual
        (mismo patrón que ChunkRepo.borrar_por_video), y al final el video."""
        video = self.videos.por_id(video_id)
        if video is None:
            return

        chunk_ids = [c.chunk_id for c in self.chunks.por_video(video_id)]
        if chunk_ids:
            if self.embedder is None or self.faiss_index is None:
                raise RuntimeError(
                    "El video tiene chunks indexados: eliminarlo requiere embedder y "
                    "faiss_index (usa los de ServiciosCache)."
                )
            version_id = self.embeddings.version_activa(
                self.embedder.model_name, self.embedder.dimensions, str(self.faiss_index.ruta)
            )
            faiss_ids = self.embeddings.faiss_ids_por_chunks(version_id, chunk_ids)
            if faiss_ids:
                self.faiss_index.remove(faiss_ids)
                self.faiss_index.save()
            self.embeddings.borrar_mapeos(version_id, chunk_ids)

        self.entities.eliminar_por_video(video_id)
        self.annotations.eliminar_por_video(video_id)
        self.chunks.borrar_por_video(video_id)  # también limpia chunks_fts (trigger)
        self.segments.borrar_por_video(video_id)
        self.videos.eliminar(video_id)
