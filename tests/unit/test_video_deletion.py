"""VideoDeletionService: borra un video y todo lo derivado (transcripción,
chunks, entidades, embeddings/FAISS, anotaciones) sin tocar el archivo."""

from uuid import uuid4

from tests.conftest import FakeEmbeddingProvider, hacer_segmentos
from videoindex.application.video_deletion_service import VideoDeletionService
from videoindex.domain.models import Annotation, SemanticChunk, Video
from videoindex.infrastructure.db.repositories import (
    AnnotationRepo,
    ChunkRepo,
    EmbeddingRepo,
    EntityRepo,
    SegmentRepo,
    VideoRepo,
)
from videoindex.infrastructure.vector.faiss_index import FaissIndex


def _video(video_id: str) -> Video:
    return Video(video_id=video_id, title="Clase 1", path="C:/v/c1.mp4", checksum=video_id)


def _armar_video_completo(con, faiss, embedder, video_id: str):
    """Un video con segmentos, chunks, entidad mencionada, anotación y
    embedding indexado en FAISS — el escenario real que hay que limpiar."""
    vrepo, srepo, crepo, erepo = VideoRepo(con), SegmentRepo(con), ChunkRepo(con), EntityRepo(con)
    v = _video(video_id)
    vrepo.guardar(v)
    srepo.guardar_lote(hacer_segmentos(video_id, [("hola Petro", 0.0, 3.0)]))
    chunk = SemanticChunk(
        chunk_id=str(uuid4()),
        video_id=video_id,
        start_time=0.0,
        end_time=3.0,
        full_text="hola Petro",
    )
    crepo.guardar_lote([chunk])
    entidad = erepo.upsert("Petro", "persona")
    erepo.registrar_mencion(entidad.entity_id, chunk.chunk_id, video_id, "Petro")
    erepo.commit()
    AnnotationRepo(con).guardar(
        Annotation(annotation_id=str(uuid4()), video_id=video_id, timestamp_s=1.0, text="nota")
    )

    emb_repo = EmbeddingRepo(con)
    version_id = emb_repo.version_activa(embedder.model_name, embedder.dimensions, str(faiss.ruta))
    vector = embedder.encode([chunk.full_text])
    faiss_id = emb_repo.siguiente_faiss_id(version_id)
    faiss.add([faiss_id], vector)
    faiss.save()
    emb_repo.mapear(version_id, [(chunk.chunk_id, faiss_id)])
    return chunk.chunk_id, faiss_id


def test_eliminar_borra_video_y_todo_lo_derivado(con, tmp_path):
    embedder = FakeEmbeddingProvider()
    faiss = FaissIndex(tmp_path / "v1.faiss", embedder.dimensions)
    video_id = str(uuid4())
    chunk_id, faiss_id = _armar_video_completo(con, faiss, embedder, video_id)

    assert faiss.ntotal == 1

    VideoDeletionService(con, embedder, faiss).eliminar(video_id)

    assert VideoRepo(con).por_id(video_id) is None
    assert SegmentRepo(con).por_video(video_id) == []
    assert ChunkRepo(con).por_video(video_id) == []
    assert AnnotationRepo(con).por_video(video_id) == []
    entidades, _ = EntityRepo(con).catalogo_de_video(video_id)
    assert entidades == {}
    assert faiss.ntotal == 0  # el vector fue removido del índice


def test_eliminar_no_afecta_otros_videos(con, tmp_path):
    embedder = FakeEmbeddingProvider()
    faiss = FaissIndex(tmp_path / "v1.faiss", embedder.dimensions)
    v1, v2 = str(uuid4()), str(uuid4())
    _armar_video_completo(con, faiss, embedder, v1)
    _armar_video_completo(con, faiss, embedder, v2)
    assert faiss.ntotal == 2

    VideoDeletionService(con, embedder, faiss).eliminar(v1)

    assert VideoRepo(con).por_id(v1) is None
    assert VideoRepo(con).por_id(v2) is not None
    assert ChunkRepo(con).por_video(v2) != []
    assert faiss.ntotal == 1  # solo se removió el vector de v1


def test_eliminar_video_inexistente_no_falla(con, tmp_path):
    embedder = FakeEmbeddingProvider()
    faiss = FaissIndex(tmp_path / "v1.faiss", embedder.dimensions)
    VideoDeletionService(con, embedder, faiss).eliminar("no-existe")  # no debe lanzar


def test_eliminar_video_sin_chunks_no_toca_faiss(con, tmp_path):
    """Un video pending/failed sin procesar no tiene chunks ni embeddings —
    eliminar no debe intentar tocar el índice FAISS en absoluto."""
    embedder = FakeEmbeddingProvider()
    faiss = FaissIndex(tmp_path / "v1.faiss", embedder.dimensions)
    video_id = str(uuid4())
    VideoRepo(con).guardar(_video(video_id))

    VideoDeletionService(con, embedder, faiss).eliminar(video_id)

    assert VideoRepo(con).por_id(video_id) is None
