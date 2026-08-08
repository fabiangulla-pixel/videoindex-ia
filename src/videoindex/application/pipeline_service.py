"""Orquestación del pipeline por video (SAD §8) — reanudable e idempotente.

Video → transcribir → diarizar → segmentar → NER+grafo → embeddings → indexar

La diarización va DESPUÉS de transcribir y no antes: reutiliza los segmentos
de Whisper como regiones de voz ya detectadas (su VAD ya corrió) en vez de
volver a buscar dónde hay habla. Es opcional — sin diarizador el pipeline
hace exactamente lo de siempre — y su fallo nunca tumba el video: una
transcripción sin etiquetas de hablante sigue siendo utilizable.

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
from videoindex.domain.diarization import asignar_hablantes
from videoindex.domain.discourse import clasificar
from videoindex.domain.models import Video
from videoindex.domain.ports import (
    DiarizationProvider,
    EmbeddingProvider,
    NERProvider,
    TranscriptionProvider,
)
from videoindex.infrastructure.db.repositories import (
    ChunkRepo,
    EmbeddingRepo,
    EntityRepo,
    SegmentRepo,
    VideoRepo,
)
from videoindex.infrastructure.media.probe import detectar_inicio_contenido
from videoindex.infrastructure.vector.faiss_index import FaissIndex

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, float], None]  # (video_id, etapa, fraccion_lote)

# Cada cuántos segmentos se vuelca la transcripción a la BD. Con ~5 s por
# segmento, 25 son unos dos minutos de audio: es lo máximo que se pierde si
# la máquina se suspende o se cierra la app a mitad.
LOTE_SEGMENTOS = 25


class PipelineService:
    def __init__(
        self,
        con: sqlite3.Connection,
        transcriptor: TranscriptionProvider,
        embedder: EmbeddingProvider,
        ner: NERProvider,
        faiss_index: FaissIndex,
        settings: Settings,
        diarizador: DiarizationProvider | None = None,
    ):
        self.con = con
        self.videos = VideoRepo(con)
        self.segmentos = SegmentRepo(con)
        self.chunks = ChunkRepo(con)
        self.entidades = EntityRepo(con)
        self.emb_repo = EmbeddingRepo(con)
        self.transcriptor = transcriptor
        self.diarizador = diarizador
        self.embedder = embedder
        self.ner = ner
        self.faiss = faiss_index
        self.settings = settings
        self._pendientes: list = []  # buffer de segmentos aún sin volcar

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
                self._procesar_video(video, progress, fraccion, len(videos))
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
        self, video: Video, progress: ProgressCallback | None, fraccion: float, n_videos: int
    ) -> None:
        def avisar(etapa: str, fraccion_interna: float = 0.0) -> None:
            log.info("video_id=%s stage=%s", video.video_id, etapa)
            if progress:
                # fraccion_interna (0..1) reparte el "hueco" de este video
                # dentro del lote (transcribir es la etapa que más tarda con
                # diferencia; el resto avisa siempre con fraccion_interna=0).
                progress(video.video_id, etapa, fraccion + fraccion_interna / n_videos)

        # Punto de reanudación ANTES de limpiar nada: si hay transcripción a
        # medias de un intento interrumpido, se conserva y se sigue desde ahí.
        reanudar_desde = self.segmentos.ultimo_instante(video.video_id)
        self._limpiar_derivados(video.video_id, conservar_segmentos=reanudar_desde > 0)

        avisar("detecting_offset")
        offset = detectar_inicio_contenido(video.path)
        self.videos.actualizar_content_start(video.video_id, offset)

        avisar("transcribing")
        self.videos.actualizar_estado(video.video_id, "transcribing")
        if reanudar_desde > 0:
            log.info(
                "video_id=%s reanudando transcripción desde %.1fs", video.video_id, reanudar_desde
            )
        self.transcriptor.transcribir(
            video.path,
            video.video_id,
            lambda f: avisar("transcribing", f),
            desde_s=reanudar_desde,
            al_segmento=self._guardar_incremental,
        )
        self._vaciar_pendientes()

        # Desde la BD, no desde lo que acaba de devolver el transcriptor: en
        # una reanudación hay que juntar lo viejo con lo nuevo.
        segs = self.segmentos.por_video(video.video_id)
        if not segs:
            raise ValueError("La transcripción no produjo segmentos (¿audio vacío?)")

        self._diarizar(video, segs, avisar)
        self.segmentos.actualizar_hablantes(segs)

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

    def _guardar_incremental(self, segmento) -> None:
        """Acumula segmentos y los vuelca cada LOTE_SEGMENTOS.

        No se guarda uno a uno (un commit por segmento son cientos de
        escrituras) ni todo al final (una hora de CPU perdida si el proceso
        muere a mitad). El lote es el término medio: se pierde, como mucho,
        el último minuto de trabajo.
        """
        self._pendientes.append(segmento)
        if len(self._pendientes) >= LOTE_SEGMENTOS:
            self._vaciar_pendientes()

    def _vaciar_pendientes(self) -> None:
        if self._pendientes:
            self.segmentos.guardar_lote(self._pendientes)
            self._pendientes = []

    def _diarizar(self, video: Video, segs: list, avisar: Callable[..., None]) -> None:
        """Etiqueta cada segmento con su hablante, si hay diarizador.

        Muta `segs` ANTES de persistirlos (una sola escritura, sin UPDATE
        posterior). Un fallo aquí se registra y se sigue: perder las
        etiquetas de hablante degrada el resultado, perder la transcripción
        entera de una hora de audio no es aceptable.
        """
        if self.diarizador is None:
            return
        # Solo se avisa la etapa a la UI; el processing_status persistido se
        # queda en 'transcribing'. Añadir 'diarizing' obligaría a reconstruir
        # la tabla videos entera (su CHECK enumera los estados válidos y
        # SQLite no permite alterarlo), y para la reanudación da igual: lo
        # único que importa es que el video no esté 'completed'.
        avisar("diarizing")
        try:
            regiones = [(s.start_time, s.end_time) for s in segs]
            turnos = self.diarizador.diarizar(
                video.path, regiones, lambda f: avisar("diarizing", f)
            )
            asignar_hablantes(segs, turnos)
            n = len({t.speaker for t in turnos})
            log.info("video_id=%s hablantes_detectados=%d", video.video_id, n)
        except Exception:
            log.exception("Diarización fallida en %s; sigue sin hablantes", video.title)

    def _limpiar_derivados(self, video_id: str, conservar_segmentos: bool = False) -> None:
        """Re-proceso idempotente: fuera chunks/vectores/segmentos previos.

        `conservar_segmentos` es lo que hace posible reanudar: los chunks y
        los vectores SIEMPRE se rehacen (dependen de la transcripción
        completa), pero la transcripción parcial ya pagada con minutos de CPU
        no se toca. Sin esta distinción, el borrado idempotente destruía
        justo el trabajo que se quería continuar.
        """
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
        if not conservar_segmentos:
            self.segmentos.borrar_por_video(video_id)
