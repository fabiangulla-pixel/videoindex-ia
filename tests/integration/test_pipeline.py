"""Pipeline E2E con fakes: idempotencia, reanudación, fallos aislados."""

from pathlib import Path
from uuid import uuid4

import pytest

from tests.conftest import FakeNERProvider, FakeTranscriptionProvider, hacer_segmentos
from videoindex.application.pipeline_service import PipelineService
from videoindex.application.search_engine import SearchEngine
from videoindex.config.settings import SearchSettings, SegmentationSettings, Settings
from videoindex.domain.models import Video
from videoindex.infrastructure.db.repositories import VideoRepo
from videoindex.infrastructure.vector.faiss_index import FaissIndex


@pytest.fixture
def settings():
    s = Settings()
    s.segmentation = SegmentationSettings(chunk_min_s=5.0, chunk_max_s=60.0)
    return s


def _pipeline(con, tmp_path: Path, fake_embedder, transcriptor, settings):
    faiss_index = FaissIndex(tmp_path / "test.faiss", fake_embedder.dimensions)
    return PipelineService(
        con, transcriptor, fake_embedder, FakeNERProvider(), faiss_index, settings
    ), faiss_index


def _alta_video(con, ruta: str, checksum: str) -> Video:
    v = Video(
        video_id=str(uuid4()),
        title=Path(ruta).stem,
        path=ruta,
        checksum=checksum,
        duration_seconds=60.0,
    )
    VideoRepo(con).guardar(v)
    return v


def _segmentos_demo(ruta: str):
    return {
        ruta: hacer_segmentos(
            "",
            [
                ("La regresión logística es un modelo supervisado de clasificación", 0.0, 8.0),
                ("Se usa para variables binarias como Aprobado o Rechazado", 8.5, 16.0),
            ],
        )
    }


def test_pipeline_completo_e_indexado(con, tmp_path, fake_embedder, settings):
    v = _alta_video(con, "C:/v/a.mp4", "ck-a")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/a.mp4"))
    pipeline, faiss_index = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    ok, fail = pipeline.procesar_lote([v])
    assert (ok, fail) == (1, 0)
    assert VideoRepo(con).por_id(v.video_id).processing_status == "completed"
    assert con.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0] >= 1
    assert faiss_index.ntotal >= 1

    # La búsqueda híbrida encuentra el contenido (ADR-003: vía SearchEngine).
    buscador = SearchEngine(con, fake_embedder, FakeNERProvider(), faiss_index, SearchSettings())
    resultados = buscador.search("regresión logística")
    assert resultados
    assert resultados[0].start_time == 0.0  # timestamp absoluto trazable


def test_reproceso_no_duplica(con, tmp_path, fake_embedder, settings):
    v = _alta_video(con, "C:/v/a.mp4", "ck-a")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/a.mp4"))
    pipeline, faiss_index = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    pipeline.procesar_lote([v])
    chunks_1 = con.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0]
    n_faiss_1 = faiss_index.ntotal

    # Forzar re-proceso (simula usuario que re-lanza a propósito)
    VideoRepo(con).actualizar_estado(v.video_id, "pending")
    transcriptor.segmentos_por_ruta = _segmentos_demo("C:/v/a.mp4")  # segmentos frescos
    pipeline.procesar_lote([v])

    assert con.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0] == chunks_1
    assert faiss_index.ntotal == n_faiss_1  # remove_ids antes de add_with_ids


def test_reanudacion_salta_completados(con, tmp_path, fake_embedder, settings):
    v = _alta_video(con, "C:/v/a.mp4", "ck-a")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/a.mp4"))
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    pipeline.procesar_lote([v])
    llamadas_1 = len(transcriptor.llamadas)
    pipeline.procesar_lote([v])  # relanzar el mismo lote
    assert len(transcriptor.llamadas) == llamadas_1  # no re-transcribe


def test_content_start_se_persiste_durante_el_pipeline(
    con, tmp_path, fake_embedder, settings, monkeypatch
):
    v = _alta_video(con, "C:/v/a.mp4", "ck-a")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/a.mp4"))
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    monkeypatch.setattr(
        "videoindex.application.pipeline_service.detectar_inicio_contenido",
        lambda ruta: 3.5,
    )
    pipeline.procesar_lote([v])
    assert VideoRepo(con).por_id(v.video_id).content_start_s == 3.5


def test_progreso_transcripcion_avanza_dentro_del_hueco_del_video(
    con, tmp_path, fake_embedder, settings
):
    """Con 2 videos en el lote, el progreso de 'transcribing' del segundo
    video debe reportarse en [0.5, 1.0], no clavado en 0.5 todo el tiempo
    (antes del fix, la fracción del lote era fija por video: no había avance
    real dentro de la transcripción de cada uno)."""
    v1 = _alta_video(con, "C:/v/a.mp4", "ck-a")
    v2 = _alta_video(con, "C:/v/b.mp4", "ck-b")
    transcriptor = FakeTranscriptionProvider(
        {**_segmentos_demo("C:/v/a.mp4"), **_segmentos_demo("C:/v/b.mp4")}
    )
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    reportes: list[tuple[str, str, float]] = []
    pipeline.procesar_lote(
        [v1, v2], progress=lambda vid, etapa, frac: reportes.append((vid, etapa, frac))
    )

    transcribiendo_v1 = [f for vid, e, f in reportes if vid == v1.video_id and e == "transcribing"]
    transcribiendo_v2 = [f for vid, e, f in reportes if vid == v2.video_id and e == "transcribing"]
    assert transcribiendo_v1 and all(0.0 <= f <= 0.5 for f in transcribiendo_v1)
    assert transcribiendo_v2 and all(0.5 <= f <= 1.0 for f in transcribiendo_v2)


def test_fallo_no_aborta_lote(con, tmp_path, fake_embedder, settings):
    v_mal = _alta_video(con, "C:/v/mal.mp4", "ck-mal")
    v_bien = _alta_video(con, "C:/v/bien.mp4", "ck-bien")
    transcriptor = FakeTranscriptionProvider(
        _segmentos_demo("C:/v/bien.mp4"), fallar_en={"C:/v/mal.mp4"}
    )
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    ok, fail = pipeline.procesar_lote([v_mal, v_bien])
    assert (ok, fail) == (1, 1)
    repo = VideoRepo(con)
    assert repo.por_id(v_mal.video_id).processing_status == "failed"
    assert repo.por_id(v_bien.video_id).processing_status == "completed"


class FakeDiarizador:
    """Reparte las regiones entre N hablantes de forma determinista; puede
    fallar a propósito para probar que el pipeline aguanta."""

    def __init__(self, n_hablantes: int = 2, fallar: bool = False):
        self.n_hablantes = n_hablantes
        self.fallar = fallar
        self.llamadas: list[str] = []

    def diarizar(self, ruta_media, regiones, progreso=None):
        from videoindex.domain.models import SpeakerTurn

        self.llamadas.append(ruta_media)
        if self.fallar:
            raise RuntimeError("modelo de voz no disponible")
        if progreso:
            progreso(1.0)
        return [
            SpeakerTurn(inicio, fin, f"SPEAKER_{i % self.n_hablantes:02d}")
            for i, (inicio, fin) in enumerate(regiones)
        ]


def test_pipeline_etiqueta_hablantes_en_segmentos_y_chunks(con, tmp_path, fake_embedder, settings):
    from videoindex.infrastructure.db.repositories import ChunkRepo, SegmentRepo

    v = _alta_video(con, "C:/v/dialogo.mp4", "ck-diarizado")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/dialogo.mp4"))
    faiss_index = FaissIndex(tmp_path / "test.faiss", fake_embedder.dimensions)
    diarizador = FakeDiarizador(n_hablantes=2)
    pipeline = PipelineService(
        con,
        transcriptor,
        fake_embedder,
        FakeNERProvider(),
        faiss_index,
        settings,
        diarizador,
    )

    ok, fail = pipeline.procesar_lote([v])
    assert (ok, fail) == (1, 0)
    assert diarizador.llamadas == ["C:/v/dialogo.mp4"]

    segmentos = SegmentRepo(con).por_video(v.video_id)
    assert [s.speaker for s in segmentos] == ["SPEAKER_00", "SPEAKER_01"]

    # Cambio de hablante = frontera dura: dos chunks, uno por voz.
    chunks = ChunkRepo(con).por_video(v.video_id)
    assert [c.speakers for c in chunks] == [["SPEAKER_00"], ["SPEAKER_01"]]


def test_si_la_diarizacion_falla_el_video_igual_se_completa(con, tmp_path, fake_embedder, settings):
    """Perder las etiquetas de hablante degrada el resultado; perder una hora
    de transcripción no es aceptable."""
    from videoindex.infrastructure.db.repositories import SegmentRepo

    v = _alta_video(con, "C:/v/roto.mp4", "ck-roto")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/roto.mp4"))
    faiss_index = FaissIndex(tmp_path / "test.faiss", fake_embedder.dimensions)
    pipeline = PipelineService(
        con,
        transcriptor,
        fake_embedder,
        FakeNERProvider(),
        faiss_index,
        settings,
        FakeDiarizador(fallar=True),
    )

    ok, fail = pipeline.procesar_lote([v])
    assert (ok, fail) == (1, 0)
    assert VideoRepo(con).por_id(v.video_id).processing_status == "completed"
    assert all(s.speaker is None for s in SegmentRepo(con).por_video(v.video_id))


def test_sin_diarizador_el_pipeline_se_comporta_como_antes(con, tmp_path, fake_embedder, settings):
    from videoindex.infrastructure.db.repositories import SegmentRepo

    v = _alta_video(con, "C:/v/solo.mp4", "ck-solo")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/solo.mp4"))
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    ok, fail = pipeline.procesar_lote([v])
    assert (ok, fail) == (1, 0)
    assert all(s.speaker is None for s in SegmentRepo(con).por_video(v.video_id))


def test_la_etapa_de_diarizacion_se_reporta_a_la_interfaz(con, tmp_path, fake_embedder, settings):
    v = _alta_video(con, "C:/v/etapas.mp4", "ck-etapas")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/etapas.mp4"))
    faiss_index = FaissIndex(tmp_path / "test.faiss", fake_embedder.dimensions)
    pipeline = PipelineService(
        con,
        transcriptor,
        fake_embedder,
        FakeNERProvider(),
        faiss_index,
        settings,
        FakeDiarizador(),
    )
    etapas: list[str] = []
    pipeline.procesar_lote([v], progress=lambda vid, etapa, frac: etapas.append(etapa))

    assert "diarizing" in etapas
    assert etapas.index("transcribing") < etapas.index("diarizing") < etapas.index("segmenting")


def _segmentos_largos(ruta: str, cuantos: int = 60):
    """Una transcripción larga, para poder cortarla por la mitad."""
    return {
        ruta: hacer_segmentos(
            "",
            [
                (f"Frase número {i} del material grabado", i * 10.0, i * 10.0 + 8.0)
                for i in range(cuantos)
            ],
        )
    }


def test_la_transcripcion_se_guarda_mientras_avanza(con, tmp_path, fake_embedder, settings):
    """Sin guardado incremental, una hora de CPU se pierde entera si el
    proceso muere; con él, lo ya transcrito queda en la BD."""
    from videoindex.infrastructure.db.repositories import SegmentRepo

    v = _alta_video(con, "C:/v/largo.mp4", "ck-largo")
    transcriptor = FakeTranscriptionProvider(_segmentos_largos("C:/v/largo.mp4"), morir_tras=40)
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)

    ok, fail = pipeline.procesar_lote([v])
    assert (ok, fail) == (0, 1)  # el video falla...

    # ...pero lo transcrito antes del corte sobrevivió (múltiplos del lote).
    guardados = SegmentRepo(con).por_video(v.video_id)
    assert len(guardados) >= 25
    assert SegmentRepo(con).ultimo_instante(v.video_id) > 0


def test_reanuda_desde_donde_se_corto_sin_repetir_lo_hecho(con, tmp_path, fake_embedder, settings):
    from videoindex.infrastructure.db.repositories import SegmentRepo

    v = _alta_video(con, "C:/v/largo.mp4", "ck-reanuda")
    segmentos = _segmentos_largos("C:/v/largo.mp4")

    # Primer intento: se corta.
    primero = FakeTranscriptionProvider(segmentos, morir_tras=40)
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, primero, settings)
    pipeline.procesar_lote([v])
    parciales = len(SegmentRepo(con).por_video(v.video_id))
    corte = SegmentRepo(con).ultimo_instante(v.video_id)
    assert primero.reanudaciones == [0.0]  # empezó desde cero

    # Segundo intento: continúa.
    segundo = FakeTranscriptionProvider(_segmentos_largos("C:/v/largo.mp4"))
    pipeline2, _ = _pipeline(con, tmp_path, fake_embedder, segundo, settings)
    ok, fail = pipeline2.procesar_lote([v])

    assert (ok, fail) == (1, 0)
    assert segundo.reanudaciones == [corte]  # arrancó donde quedó, no en 0
    finales = SegmentRepo(con).por_video(v.video_id)
    assert len(finales) == 60  # están los 60, sin duplicados
    assert len({s.segment_id for s in finales}) == 60
    assert [s.start_time for s in finales] == sorted(s.start_time for s in finales)
    assert parciales < 60


def test_un_video_completado_se_reprocesa_desde_cero(con, tmp_path, fake_embedder, settings):
    """Reanudar es para lo interrumpido. Si se re-procesa un video ya
    terminado (otro modelo, otra configuración), no debe quedar mezcla."""
    from videoindex.infrastructure.db.repositories import SegmentRepo, VideoRepo

    v = _alta_video(con, "C:/v/a.mp4", "ck-reproceso")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/a.mp4"))
    pipeline, _ = _pipeline(con, tmp_path, fake_embedder, transcriptor, settings)
    pipeline.procesar_lote([v])
    assert VideoRepo(con).por_id(v.video_id).processing_status == "completed"

    # Forzar re-proceso: se marca como pendiente y se vuelve a lanzar.
    VideoRepo(con).actualizar_estado(v.video_id, "pending")
    SegmentRepo(con).borrar_por_video(v.video_id)
    otro = FakeTranscriptionProvider(_segmentos_demo("C:/v/a.mp4"))
    pipeline2, _ = _pipeline(con, tmp_path, fake_embedder, otro, settings)
    pipeline2.procesar_lote([VideoRepo(con).por_id(v.video_id)])

    assert otro.reanudaciones == [0.0]
    assert len(SegmentRepo(con).por_video(v.video_id)) == 2


def test_los_hablantes_se_escriben_sobre_los_segmentos_ya_guardados(
    con, tmp_path, fake_embedder, settings
):
    """La transcripción se persiste antes de saber quién habla; la
    diarización tiene que poder completarla después con un UPDATE."""
    from videoindex.infrastructure.db.repositories import SegmentRepo

    v = _alta_video(con, "C:/v/dialogo.mp4", "ck-update-hablantes")
    transcriptor = FakeTranscriptionProvider(_segmentos_demo("C:/v/dialogo.mp4"))
    faiss_index = FaissIndex(tmp_path / "test.faiss", fake_embedder.dimensions)
    pipeline = PipelineService(
        con,
        transcriptor,
        fake_embedder,
        FakeNERProvider(),
        faiss_index,
        settings,
        FakeDiarizador(n_hablantes=2),
    )
    pipeline.procesar_lote([v])

    guardados = SegmentRepo(con).por_video(v.video_id)
    assert [s.speaker for s in guardados] == ["SPEAKER_00", "SPEAKER_01"]
