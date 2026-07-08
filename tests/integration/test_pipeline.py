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
