"""Workers QThread: el pipeline y la búsqueda nunca bloquean la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from videoindex.config import paths
from videoindex.config.settings import SETTINGS


class ServiciosCache:
    """Construcción perezosa y única de los modelos pesados (embeddings, NER,
    índice FAISS) — son costosos de cargar y seguros de compartir entre hilos
    para lectura.

    SQLite NO se cachea aquí: sqlite3 prohíbe usar una conexión fuera del
    hilo que la creó, así que cada QThread abre y cierra la suya propia
    (ver conectar() + SearchEngine(con, ...) en cada worker de abajo).
    """

    _instancia = None

    def __init__(self):
        from videoindex.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider
        from videoindex.infrastructure.ner.spacy_ner_provider import SpacyNERProvider
        from videoindex.infrastructure.vector.faiss_index import FaissIndex

        paths.ensure_dirs()
        self.embedder = LocalEmbeddingProvider()
        self.ner = SpacyNERProvider()
        self.faiss = FaissIndex(paths.FAISS_DIR / "v1.faiss", self.embedder.dimensions)

    @classmethod
    def obtener(cls) -> ServiciosCache:
        if cls._instancia is None:
            cls._instancia = cls()
        return cls._instancia


def _crear_buscador(servicios: ServiciosCache, con):
    """SearchEngine nuevo, con la conexión del hilo actual, reusando modelos."""
    from videoindex.application.search_engine import SearchEngine

    return SearchEngine(con, servicios.embedder, servicios.ner, servicios.faiss, SETTINGS.search)


class EscaneoWorker(QThread):
    """Escanea una carpeta (checksums pueden tardar en archivos grandes o en
    red, p. ej. Google Drive sin caché local) y reporta el resumen."""

    progreso = Signal(int, int, str)  # indice, total, nombre_archivo
    terminado = Signal(object)  # ResultadoIngesta
    fallo = Signal(str)

    def __init__(self, carpeta: str, curso: str | None = None, project_id: str | None = None):
        super().__init__()
        self.carpeta = carpeta
        self.curso = curso
        self.project_id = project_id

    def run(self):
        con = None
        try:
            from videoindex.application.ingest_service import IngestService
            from videoindex.infrastructure.db.connection import conectar

            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            resultado = IngestService(con).escanear_carpeta(
                self.carpeta, self.curso, self.progreso.emit, self.project_id
            )
            self.terminado.emit(resultado)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


class DescargaWorker(QThread):
    """Baja el audio de una o varias URLs y las da de alta en la biblioteca.

    Descarga y alta van en el MISMO hilo a propósito: el checksum del archivo
    recién bajado es lo que hace idempotente la ingesta, y separarlo en dos
    pasos abriría la puerta a re-descargar lo que ya está.
    """

    progreso = Signal(int, int, str)  # indice, total, mensaje
    terminado = Signal(object, list)  # ResultadoIngesta, list[str] de errores
    fallo = Signal(str)

    def __init__(self, urls: list[str], project_id: str | None = None):
        super().__init__()
        self.urls = urls
        self.project_id = project_id

    def run(self):
        con = None
        try:
            from videoindex.application.ingest_service import IngestService, ResultadoIngesta
            from videoindex.infrastructure.db.connection import conectar
            from videoindex.infrastructure.media.youtube import descargar_audio

            paths.ensure_dirs()
            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            servicio = IngestService(con)
            total = ResultadoIngesta()
            errores: list[str] = []

            for i, url in enumerate(self.urls, 1):
                self.progreso.emit(i, len(self.urls), f"Descargando {url}")
                try:
                    media = descargar_audio(
                        url,
                        paths.DESCARGAS_DIR,
                        lambda f, texto, i=i: self.progreso.emit(i, len(self.urls), texto),
                    )
                except Exception as exc:
                    # Una URL rota no puede tumbar el resto del lote (mismo
                    # criterio que un video malo en procesar_lote).
                    errores.append(f"{url}: {exc}")
                    continue
                self.progreso.emit(i, len(self.urls), f"Registrando «{media.titulo}»")
                parcial = servicio.registrar_descarga(media, project_id=self.project_id)
                total.nuevos += parcial.nuevos
                total.ya_completados += parcial.ya_completados
                total.pendientes_previos += parcial.pendientes_previos

            self.terminado.emit(total, errores)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


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
        con = None
        try:
            from videoindex.application.pipeline_service import PipelineService
            from videoindex.application.time_estimator import TimeEstimator
            from videoindex.config.settings import factor_tiempo
            from videoindex.infrastructure.db.connection import conectar
            from videoindex.infrastructure.db.repositories import VideoRepo
            from videoindex.infrastructure.diarization.ecapa_provider import crear_diarizador
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
                SETTINGS.transcription.beam_size,
                SETTINGS.transcription.initial_prompt,
                SETTINGS.transcription.condition_on_previous_text,
            )
            pipeline = PipelineService(
                con,
                transcriptor,
                servicios.embedder,
                servicios.ner,
                servicios.faiss,
                SETTINGS,
                crear_diarizador(SETTINGS.diarization),
            )
            estimador = TimeEstimator(
                factor_tiempo(SETTINGS.transcription.modelo, SETTINGS.diarization.activa)
            )
            ok, fail = pipeline.procesar_lote(videos, self.progreso.emit, estimador.calibrar)
            self.terminado.emit(ok, fail)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


class BusquedaWorker(QThread):
    resultados = Signal(list)  # list[SearchResult]
    fallo = Signal(str)

    def __init__(self, query: str, k: int = 100, project_id: str | None = "__todos__"):
        super().__init__()
        self.query = query
        self.k = k
        self.project_id = project_id

    def run(self):
        con = None
        try:
            from videoindex.infrastructure.db.connection import conectar

            servicios = ServiciosCache.obtener()
            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            buscador = _crear_buscador(servicios, con)
            resultados = buscador.search(self.query, self.k, self.project_id)
            self.resultados.emit(resultados)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


class EliminarVideoWorker(QThread):
    """Borra un video y todo lo derivado (transcripción, chunks, entidades,
    embeddings/FAISS, anotaciones). El archivo en disco no se toca aquí —
    borrarlo también, si el usuario lo pidió, lo hace la vista tras recibir
    'terminado' (I/O de archivo simple, no necesita hilo aparte)."""

    terminado = Signal(str)  # video_id
    fallo = Signal(str)

    def __init__(self, video_id: str):
        super().__init__()
        self.video_id = video_id

    def run(self):
        con = None
        try:
            from videoindex.application.video_deletion_service import VideoDeletionService
            from videoindex.infrastructure.db.connection import conectar

            servicios = ServiciosCache.obtener()
            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            VideoDeletionService(con, servicios.embedder, servicios.faiss).eliminar(self.video_id)
            self.terminado.emit(self.video_id)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


class DetectarInicioWorker(QThread):
    """Detecta el primer frame no-negro para pre-llenar la marca de inicio
    del diálogo de recorte. Solo lee frames del inicio del archivo (rápido)
    y detectar_inicio_contenido nunca lanza: 0.0 = sin sugerencia."""

    listo = Signal(float)  # offset_s (0.0 = sin negro inicial detectado)

    def __init__(self, ruta_video: str):
        super().__init__()
        self.ruta_video = ruta_video

    def run(self):
        from videoindex.infrastructure.media.probe import detectar_inicio_contenido

        self.listo.emit(detectar_inicio_contenido(self.ruta_video))


class TrimWorker(QThread):
    """Recorta un video (remux sin re-codificar, archivo NUEVO) y lo
    reemplaza en la biblioteca: alta del recortado con el proyecto/curso del
    original + baja del original (su archivo en disco no se toca).

    El borrado del original es ligero (pending/failed no tienen embeddings):
    solo carga ServiciosCache si el video sí llegó a indexar chunks."""

    progreso = Signal(float)  # fraccion 0..1 del remux
    terminado = Signal(str)  # titulo del video recortado
    fallo = Signal(str)

    def __init__(self, video_id: str, ruta_original: str, inicio_s: float, fin_s: float | None):
        super().__init__()
        self.video_id = video_id
        self.ruta_original = ruta_original
        self.inicio_s = inicio_s
        self.fin_s = fin_s

    def run(self):
        con = None
        try:
            from videoindex.application.trim_service import (
                generar_ruta_recorte,
                registrar_recorte,
            )
            from videoindex.application.video_deletion_service import VideoDeletionService
            from videoindex.infrastructure.db.connection import conectar
            from videoindex.infrastructure.db.repositories import ChunkRepo, VideoRepo
            from videoindex.infrastructure.media.trimmer import recortar_video

            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            original = VideoRepo(con).por_id(self.video_id)
            if original is None:
                raise ValueError("El video ya no está en la biblioteca.")

            destino = generar_ruta_recorte(self.ruta_original)
            recortar_video(
                self.ruta_original, destino, self.inicio_s, self.fin_s, self.progreso.emit
            )

            nuevo = registrar_recorte(con, original, destino)
            if ChunkRepo(con).por_video(self.video_id):
                servicios = ServiciosCache.obtener()
                deletion = VideoDeletionService(con, servicios.embedder, servicios.faiss)
            else:
                deletion = VideoDeletionService(con, None, None)
            deletion.eliminar(self.video_id)
            self.terminado.emit(nuevo.title)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


class DossierRecopilarWorker(QThread):
    """Fase 1 del Dossier: recopila TODAS las entidades del video y sus
    chunks como evidencia (no necesita embedder/NER/FAISS, no usa
    ServiciosCache — solo SQL)."""

    listo = Signal(str, list)  # video_title, list[tuple[Entity, list[Evidence]]]
    fallo = Signal(str)

    def __init__(self, video_id: str, video_title: str):
        super().__init__()
        self.video_id = video_id
        self.video_title = video_title

    def run(self):
        con = None
        try:
            from videoindex.application.dossier_service import DossierService
            from videoindex.infrastructure.db.connection import conectar

            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            servicio = DossierService(con, SETTINGS.rag)
            entidades_evidencia = servicio.recopilar_evidencia_por_entidad(
                self.video_id, self.video_title
            )
            self.listo.emit(self.video_title, entidades_evidencia)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()


class DossierGenerarWorker(QThread):
    """Fase 2 del Dossier: una llamada al LLM por entidad con evidencia,
    misma instancia de provider para las N llamadas (usages() acumula)."""

    listo = Signal(str, list, object)  # video_title, list[DossierEntidad], CostoReal
    fallo = Signal(str)

    def __init__(self, video_title: str, entidades_evidencia: list, proveedor: str, modelo: str):
        super().__init__()
        self.video_title = video_title
        self.entidades_evidencia = entidades_evidencia
        self.proveedor = proveedor
        self.modelo = modelo

    def run(self):
        con = None
        try:
            from videoindex.application.dossier_service import DossierService
            from videoindex.infrastructure.db.connection import conectar
            from videoindex.infrastructure.llm.providers import crear_provider

            con = conectar(paths.DB_PATH)  # conexión propia de este hilo
            servicio = DossierService(con, SETTINGS.rag)
            llm = crear_provider(self.proveedor, self.modelo)
            dossier, costo_real = servicio.generar(self.entidades_evidencia, llm, self.proveedor)
            self.listo.emit(self.video_title, dossier, costo_real)
        except Exception as exc:
            self.fallo.emit(str(exc))
        finally:
            if con is not None:
                con.close()
