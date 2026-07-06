"""Orquestación del pipeline por video (SAD §8) — reanudable e idempotente.

Video → transcribir → segmentar → NER+grafo → embeddings → indexar → completed

Reanudación: el checkpoint es el `processing_status` por video en la BD
(patrón de ReactivosFlow adaptado: aquí la unidad de trabajo es el video y
SQLite ya nos da la persistencia incremental; matar el proceso y relanzar
retoma los videos no completados sin re-transcribir los terminados).

Idempotencia: antes de re-procesar un video se borran sus derivados
(segmentos, chunks, vectores FAISS vía remove_ids). La transcripción original
de un video completado nunca se toca.

Whisper en CPU satura los cores → los videos se procesan secuencialmente;
el paralelismo vive dentro de faster-whisper y sentence-transformers.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from itertools import combinations

from videoindex.config.settings import Settings
from videoindex.domain import segmentation
from videoindex.domain.discourse import clasificar
from videoindex.domain.models import Video
from videoindex.domain.ports import EmbeddingProvider, NERProvider, TranscriptionProvider
from videoindex.infrastructure.db.repositories import (
    ChunkRepo,
    EmbeddingRepo,
    EntityRepo,
    SegmentRepo,
    VideoRepo,
)
from videoindex.infrastructure.vector.faiss_index import FaissIndex

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, float], None]  # (video_id, etapa, fraccion_lote)


class PipelineService:
    def __init__(
        self,
        con: sqlite3.Connection,
        transcriptor: TranscriptionProvider,
        embedder: EmbeddingProvider,
        ner: NERProvider,
        faiss_index: FaissIndex,
        settings: Settings,
    ):
        self.con = con
        self.videos = VideoRepo(con)
        self.segmentos = SegmentRepo(con)
        self.chunks = ChunkRepo(con)
        self.entidades = EntityRepo(con)
        self.emb_repo = EmbeddingRepo(con)
        self.transcriptor = transcriptor
        self.embedder = embedder
        self.ner = ner
        self.faiss = faiss_index
        self.settings = settings

    def procesar_lote(
        self,
        videos: list[Video],
        progress: ProgressCallback | None = None,
        calibrar: Callable[[float, float], None] | None = None,
    ) -> tuple[int, int]:
        """Procesa videos pendientes. Devuelve (completados, fallidos)."""
        ok, fail = 0, 0
        for i, video in enumerate(videos):
            actual = self.videos.por_id(video.video_id)
            if actual and actual.processing_status == "completed":
                continue  # reanudación: no re-pagar tiempo
            fraccion = i / len(videos) if videos else 1.0
            try:
                inicio = time.time()
                self._procesar_video(video, progress, fraccion)
                transcurrido = time.time() - inicio
                if calibrar and video.duration_seconds:
                    calibrar(video.duration_seconds, transcurrido)
                ok += 1
            except Exception as exc:  # un video malo no aborta el lote
                log.exception("Fallo procesando %s", video.title)
                self.videos.actualizar_estado(video.video_id, "failed", str(exc))
                fail += 1
        return ok, fail

    def _procesar_video(
        self, video: Video, progress: ProgressCallback | None, fraccion: float
    ) -> None:
        def avisar(etapa: str) -> None:
            log.info("video_id=%s stage=%s", video.video_id, etapa)
            if progress:
                progress(video.video_id, etapa, fraccion)

        self._limpiar_derivados(video.video_id)

        avisar("transcribing")
        self.videos.actualizar_estado(video.video_id, "transcribing")
        segs = self.transcriptor.transcribir(video.path, video.video_id)
        if not segs:
            raise ValueError("La transcripción no produjo segmentos (¿audio vacío?)")
        self.segmentos.guardar_lote(segs)

        avisar("segmenting")
        self.videos.actualizar_estado(video.video_id, "segmenting")
        chunks = segmentation.segmentar(segs, self.embedder.encode, self.settings.segmentation)
        for c in chunks:
            c.summary = segmentation.resumen_local(c.full_text)
            c.discourse_type = clasificar(c.full_text)
        self.chunks.guardar_lote(chunks)

        avisar("extracting")
        self.videos.actualizar_estado(video.video_id, "extracting")
        for c in chunks:
            ents = self.ner.extraer(c.full_text)
            ids_entidades = []
            for superficie, tipo in ents:
                ent = self.entidades.upsert(superficie, tipo)
                self.entidades.registrar_mencion(
                    ent.entity_id, c.chunk_id, video.video_id, superficie
                )
                ids_entidades.append(ent.entity_id)
            # KG simple del MVP: co-ocurrencia dentro del chunk (ADR-005)
            for a, b in combinations(sorted(set(ids_entidades)), 2):
                self.entidades.registrar_coocurrencia(a, b)
        self.entidades.commit()

        avisar("indexing")
        self.videos.actualizar_estado(video.video_id, "indexing")
        version_id = self.emb_repo.version_activa(
            self.embedder.model_name, self.embedder.dimensions, str(self.faiss.ruta)
        )
        vectores = self.embedder.encode([c.full_text for c in chunks])
        base = self.emb_repo.siguiente_faiss_id(version_id)
        faiss_ids = list(range(base, base + len(chunks)))
        self.faiss.add(faiss_ids, vectores)
        self.faiss.save()
        self.emb_repo.mapear(
            version_id, list(zip([c.chunk_id for c in chunks], faiss_ids, strict=True))
        )

        self.videos.actualizar_estado(video.video_id, "completed")
        avisar("completed")

    def _limpiar_derivados(self, video_id: str) -> None:
        """Re-proceso idempotente: fuera chunks/vectores/segmentos previos."""
        chunk_ids = [
            r["chunk_id"]
            for r in self.con.execute(
                "SELECT chunk_id FROM semantic_chunks WHERE video_id = ?", (video_id,)
            )
        ]
        if chunk_ids:
            row = self.con.execute(
                "SELECT version_id FROM embedding_versions WHERE is_active = 1"
            ).fetchone()
            if row:
                faiss_ids = self.emb_repo.faiss_ids_por_chunks(row["version_id"], chunk_ids)
                self.faiss.remove(faiss_ids)
                self.faiss.save()
                self.emb_repo.borrar_mapeos(row["version_id"], chunk_ids)
        self.chunks.borrar_por_video(video_id)
        self.segmentos.borrar_por_video(video_id)
