"""SearchEngine: k solicitado no debe cortarse antes de fusionar por el
techo de candidatos_por_fuente (bug real: con k > candidatos_por_fuente,
FAISS/FTS solo traían candidatos_por_fuente y nunca llegaban a fusionar
suficientes para cumplir k, aunque hubiera más chunks en la BD)."""

from uuid import uuid4

from tests.conftest import FakeNERProvider
from videoindex.application.search_engine import SearchEngine
from videoindex.config.settings import SearchSettings
from videoindex.domain.models import SemanticChunk, Video
from videoindex.infrastructure.db.repositories import ChunkRepo, EmbeddingRepo, VideoRepo
from videoindex.infrastructure.vector.faiss_index import FaissIndex


def _indexar_chunks(con, faiss, embedder, video_id: str, textos: list[str]):
    crepo = ChunkRepo(con)
    chunks = [
        SemanticChunk(
            chunk_id=str(uuid4()),
            video_id=video_id,
            start_time=float(i * 10),
            end_time=float(i * 10 + 5),
            full_text=texto,
        )
        for i, texto in enumerate(textos)
    ]
    crepo.guardar_lote(chunks)

    emb_repo = EmbeddingRepo(con)
    version_id = emb_repo.version_activa(embedder.model_name, embedder.dimensions, str(faiss.ruta))
    vectores = embedder.encode(textos)
    base = emb_repo.siguiente_faiss_id(version_id)
    faiss_ids = list(range(base, base + len(chunks)))
    faiss.add(faiss_ids, vectores)
    faiss.save()
    emb_repo.mapear(version_id, list(zip([c.chunk_id for c in chunks], faiss_ids, strict=True)))


def test_search_con_k_mayor_que_candidatos_por_fuente_no_se_corta(con, tmp_path, fake_embedder):
    """candidatos_por_fuente=5 pero hay 20 chunks y se pide k=20: antes del
    fix, n quedaba fijo en 5 y como máximo 5 candidatos llegaban a fusionar."""
    video_id = str(uuid4())
    VideoRepo(con).guardar(Video(video_id=video_id, title="v", path="C:/v.mp4", checksum="ck"))
    textos = [f"palabra clave numero {i}" for i in range(20)]
    faiss = FaissIndex(tmp_path / "v1.faiss", fake_embedder.dimensions)
    _indexar_chunks(con, faiss, fake_embedder, video_id, textos)

    settings = SearchSettings(candidatos_por_fuente=5)
    buscador = SearchEngine(con, fake_embedder, FakeNERProvider(), faiss, settings)

    resultados = buscador.search("palabra clave", k=20)
    assert len(resultados) == 20


def test_search_k_menor_respeta_el_limite(con, tmp_path, fake_embedder):
    video_id = str(uuid4())
    VideoRepo(con).guardar(Video(video_id=video_id, title="v", path="C:/v.mp4", checksum="ck"))
    textos = [f"palabra clave numero {i}" for i in range(20)]
    faiss = FaissIndex(tmp_path / "v1.faiss", fake_embedder.dimensions)
    _indexar_chunks(con, faiss, fake_embedder, video_id, textos)

    buscador = SearchEngine(con, fake_embedder, FakeNERProvider(), faiss, SearchSettings())
    resultados = buscador.search("palabra clave", k=3)
    assert len(resultados) == 3


def test_search_filtra_por_proyecto(con, tmp_path, fake_embedder):
    """Cada proyecto es un corpus aparte: buscar en el proyecto A no debe
    devolver chunks de videos del proyecto B ni de videos sin proyecto."""
    from videoindex.infrastructure.db.repositories import ProjectRepo

    proyecto_a = ProjectRepo(con).crear("Agentes IA")
    proyecto_b = ProjectRepo(con).crear("Tarot")
    v_a, v_b, v_sin = str(uuid4()), str(uuid4()), str(uuid4())
    VideoRepo(con).guardar(
        Video(
            video_id=v_a,
            title="a",
            path="C:/a.mp4",
            checksum="ck-a",
            project_id=proyecto_a.project_id,
        )
    )
    VideoRepo(con).guardar(
        Video(
            video_id=v_b,
            title="b",
            path="C:/b.mp4",
            checksum="ck-b",
            project_id=proyecto_b.project_id,
        )
    )
    VideoRepo(con).guardar(Video(video_id=v_sin, title="s", path="C:/s.mp4", checksum="ck-s"))

    faiss = FaissIndex(tmp_path / "v1.faiss", fake_embedder.dimensions)
    _indexar_chunks(con, faiss, fake_embedder, v_a, ["agentes procesan la palabra clave"])
    _indexar_chunks(con, faiss, fake_embedder, v_b, ["el tarot usa la palabra clave"])
    _indexar_chunks(con, faiss, fake_embedder, v_sin, ["texto suelto con la palabra clave"])

    buscador = SearchEngine(con, fake_embedder, FakeNERProvider(), faiss, SearchSettings())

    solo_a = buscador.search("palabra clave", k=10, project_id=proyecto_a.project_id)
    assert solo_a and all(r.video_id == v_a for r in solo_a)

    sin_proyecto = buscador.search("palabra clave", k=10, project_id=None)
    assert sin_proyecto and all(r.video_id == v_sin for r in sin_proyecto)

    todos = buscador.search("palabra clave", k=10)  # default "__todos__"
    assert {r.video_id for r in todos} == {v_a, v_b, v_sin}
