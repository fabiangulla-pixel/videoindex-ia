"""Workers QThread: el pipeline y la búsqueda nunca bloquean la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from videoindex.config import paths
from videoindex.config.settings import SETTINGS


class ServiciosCache:
    """Construcción perezosa y única de los servicios pesados (modelos)."""

    _instancia = None

    def __init__(self):
        from videoindex.application.search_engine import SearchEngine
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider
        from videoindex.infrastructure.ner.spacy_ner_provider import SpacyNERProvider
        from videoindex.infrastructure.vector.faiss_index import FaissIndex

        paths.ensure_dirs()
        self.con = conectar(paths.DB_PATH)
        self.embedder = LocalEmbeddingProvider()
        self.ner = SpacyNERProvider()
        self.faiss = FaissIndex(paths.FAISS_DIR / "v1.faiss", self.embedder.dimensions)
        self.buscador = SearchEngine(self.con, self.embedder, self.ner, self.faiss, SETTINGS.search)

    @classmethod
    def obtener(cls) -> ServiciosCache:
        if cls._instancia is None:
            cls._instancia = cls()
        return cls._instancia


class EscaneoWorker(QThread):
    """Escanea una carpeta (checksums pueden tardar en archivos grandes o en
    red, p. ej. Google Drive sin caché local) y reporta el resumen."""

    progreso = Signal(int, int, str)  # indice, total, nombre_archivo
    terminado = Signal(object)  # ResultadoIngesta
    fallo = Signal(str)

    def __init__(self, carpeta: str, curso: str | None = None):
        super().__init__()
        self.carpeta = carpeta
        self.curso = curso

    def run(self):
        try:
            from videoindex.application.ingest_service import IngestService
            from videoindex.infrastructure.db.connection import conectar

            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            resultado = IngestService(con).escanear_carpeta(
                self.carpeta, self.curso, self.progreso.emit
            )
            con.close()
            self.terminado.emit(resultado)
        except Exception as exc:
            self.fallo.emit(str(exc))


class PipelineWorker(QThread):
    """Procesa el lote completo; emite progreso por etapa y por video.

    OJO: usa su PROPIA conexión SQLite (sqlite3 no comparte conexiones entre
    hilos) pero comparte el índice FAISS y los modelos del caché.
    """

    progreso = Signal(str, str, float)  # video_id, etapa, fraccion del lote
    terminado = Signal(int, int)  # ok, fallidos
    fallo = Signal(str)

    def __init__(self, video_ids: list[str]):
        super().__init__()
        self.video_ids = video_ids

    def run(self):
        try:
            from videoindex.application.pipeline_service import PipelineService
            from videoindex.application.time_estimator import TimeEstimator
            from videoindex.infrastructure.db.connection import conectar
            from videoindex.infrastructure.db.repositories import VideoRepo
            from videoindex.infrastructure.transcription.faster_whisper_provider import (
                FasterWhisperProvider,
            )

            servicios = ServiciosCache.obtener()
            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            repo = VideoRepo(con)
            videos = [v for vid in self.video_ids if (v := repo.por_id(vid))]

            transcriptor = FasterWhisperProvider(
                SETTINGS.transcription.modelo,
                SETTINGS.transcription.idioma,
                SETTINGS.transcription.compute_type,
            )
            pipeline = PipelineService(
                con, transcriptor, servicios.embedder, servicios.ner, servicios.faiss, SETTINGS
            )
            estimador = TimeEstimator(SETTINGS.transcription.factor_tiempo_inicial)
            ok, fail = pipeline.procesar_lote(videos, self.progreso.emit, estimador.calibrar)
            con.close()
            self.terminado.emit(ok, fail)
        except Exception as exc:
            self.fallo.emit(str(exc))


class BusquedaWorker(QThread):
    resultados = Signal(list)  # list[SearchResult]
    fallo = Signal(str)

    def __init__(self, query: str, k: int = 10):
        super().__init__()
        self.query = query
        self.k = k

    def run(self):
        try:
            servicios = ServiciosCache.obtener()
            self.resultados.emit(servicios.buscador.search(self.query, self.k))
        except Exception as exc:
            self.fallo.emit(str(exc))
