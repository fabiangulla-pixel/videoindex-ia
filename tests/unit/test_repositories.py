"""Repositorios + FTS5 + triggers, sobre SQLite en memoria."""

from uuid import uuid4

from tests.conftest import hacer_segmentos
from videoindex.domain.models import SemanticChunk, Video
from videoindex.infrastructure.db.repositories import (
    ChunkRepo,
    EmbeddingRepo,
    EntityRepo,
    SegmentRepo,
    VideoRepo,
    normalizar_label,
)


def _video(checksum="abc123") -> Video:
    return Video(video_id=str(uuid4()), title="Clase 1", path="C:/v/c1.mp4", checksum=checksum)


def test_normalizar_label():
    assert normalizar_label("García Márquez") == "garcia marquez"
    assert normalizar_label("  BOGOTÁ ") == "bogota"


def test_video_idempotente_por_checksum(con):
    repo = VideoRepo(con)
    v1 = _video()
    repo.guardar(v1)
    # mismo checksum, otra ruta (archivo movido) → actualiza, no duplica
    v2 = _video()
    v2.path = "D:/otro/c1.mp4"
    repo.guardar(v2)
    assert len(repo.listar()) == 1
    assert repo.por_checksum("abc123").path == "D:/otro/c1.mp4"


def test_estado_y_error(con):
    repo = VideoRepo(con)
    v = _video()
    repo.guardar(v)
    repo.actualizar_estado(v.video_id, "failed", "audio vacío")
    assert repo.por_id(v.video_id).processing_status == "failed"


def test_content_start_se_guarda_y_lee(con):
    repo = VideoRepo(con)
    v = _video()
    repo.guardar(v)
    assert repo.por_id(v.video_id).content_start_s is None  # aún no detectado
    repo.actualizar_content_start(v.video_id, 4.5)
    assert repo.por_id(v.video_id).content_start_s == 4.5


def test_fts_encuentra_sin_tildes(con):
    vrepo, crepo = VideoRepo(con), ChunkRepo(con)
    v = _video()
    vrepo.guardar(v)
    crepo.guardar_lote(
        [
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=v.video_id,
                start_time=0.0,
                end_time=60.0,
                full_text="La canción popular como patrimonio inmaterial de la nación",
            )
        ]
    )
    hits = crepo.buscar_fts("cancion", k=10)  # sin tilde
    assert len(hits) == 1
    # BM25 crudo es negativo (menor = mejor)
    assert next(iter(hits.values())) < 0


def test_fts_query_con_comillas_dobles_no_rompe_sintaxis(con):
    vrepo, crepo = VideoRepo(con), ChunkRepo(con)
    v = _video()
    vrepo.guardar(v)
    crepo.guardar_lote(
        [
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=v.video_id,
                start_time=0.0,
                end_time=60.0,
                full_text='El profesor dijo "hola" al empezar la clase',
            )
        ]
    )
    # Una búsqueda con comillas literales no debe lanzar OperationalError.
    hits = crepo.buscar_fts('dijo "hola"', k=10)
    assert len(hits) == 1


def test_fts_trigger_delete(con):
    vrepo, crepo = VideoRepo(con), ChunkRepo(con)
    v = _video()
    vrepo.guardar(v)
    c = SemanticChunk(
        chunk_id=str(uuid4()),
        video_id=v.video_id,
        start_time=0.0,
        end_time=10.0,
        full_text="tema efímero",
    )
    crepo.guardar_lote([c])
    assert crepo.buscar_fts("efimero", 10)
    crepo.borrar_por_video(v.video_id)
    assert not crepo.buscar_fts("efimero", 10)


def test_segmentos_roundtrip(con):
    vrepo, srepo = VideoRepo(con), SegmentRepo(con)
    v = _video()
    vrepo.guardar(v)
    segs = hacer_segmentos(v.video_id, [("hola", 0.0, 3.0), ("mundo", 3.5, 6.0)])
    srepo.guardar_lote(segs)
    leidos = srepo.por_video(v.video_id)
    assert [s.clean_text for s in leidos] == ["hola", "mundo"]
    assert leidos[0].start_time == 0.0  # absolutos, orden temporal


def test_entidades_upsert_pliega_acentos(con):
    erepo = EntityRepo(con)
    e1 = erepo.upsert("García Márquez", "persona")
    e2 = erepo.upsert("garcia marquez", "persona")
    assert e1.entity_id == e2.entity_id  # misma entidad canónica


def test_coocurrencia_acumula_peso(con):
    erepo = EntityRepo(con)
    a = erepo.upsert("Petro", "persona")
    b = erepo.upsert("Bogotá", "lugar")
    erepo.registrar_coocurrencia(a.entity_id, b.entity_id)
    erepo.registrar_coocurrencia(b.entity_id, a.entity_id)  # orden inverso, mismo par
    erepo.commit()
    peso = con.execute("SELECT weight FROM relations").fetchone()[0]
    assert peso == 2


def test_embedding_version_unica_activa(con):
    repo = EmbeddingRepo(con)
    v1 = repo.version_activa("modelo-a", 384, "a.faiss")
    v1_bis = repo.version_activa("modelo-a", 384, "a.faiss")
    assert v1 == v1_bis  # no crea duplicados
    assert repo.siguiente_faiss_id(v1) == 0


def test_chunk_repo_por_video_ordena_por_start_time(con):
    vrepo, crepo = VideoRepo(con), ChunkRepo(con)
    v = _video()
    vrepo.guardar(v)
    crepo.guardar_lote(
        [
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=v.video_id,
                start_time=30.0,
                end_time=40.0,
                full_text="segundo tema",
            ),
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=v.video_id,
                start_time=0.0,
                end_time=10.0,
                full_text="primer tema",
            ),
        ]
    )
    chunks = crepo.por_video(v.video_id)
    assert [c.full_text for c in chunks] == ["primer tema", "segundo tema"]
    assert chunks[0].start_time == 0.0  # absolutos, orden temporal


def test_entidades_de_video_agrupa_chunks_ordenados_por_tiempo(con):
    vrepo, crepo, erepo = VideoRepo(con), ChunkRepo(con), EntityRepo(con)
    v = _video()
    vrepo.guardar(v)
    c1 = SemanticChunk(
        chunk_id=str(uuid4()),
        video_id=v.video_id,
        start_time=0.0,
        end_time=10.0,
        full_text="Petro habla primero",
    )
    c2 = SemanticChunk(
        chunk_id=str(uuid4()),
        video_id=v.video_id,
        start_time=20.0,
        end_time=30.0,
        full_text="Petro habla despues",
    )
    c3 = SemanticChunk(
        chunk_id=str(uuid4()),
        video_id=v.video_id,
        start_time=5.0,
        end_time=15.0,
        full_text="Bogota se menciona aqui",
    )
    crepo.guardar_lote([c1, c2, c3])

    petro = erepo.upsert("Petro", "persona")
    bogota = erepo.upsert("Bogotá", "lugar")
    erepo.registrar_mencion(petro.entity_id, c1.chunk_id, v.video_id, "Petro")
    erepo.registrar_mencion(petro.entity_id, c2.chunk_id, v.video_id, "Petro")
    erepo.registrar_mencion(bogota.entity_id, c3.chunk_id, v.video_id, "Bogotá")

    entidades, chunks_por_entidad = erepo.catalogo_de_video(v.video_id)

    assert set(entidades) == {petro.entity_id, bogota.entity_id}
    assert entidades[petro.entity_id].label == "Petro"
    # orden cronológico dentro de la misma entidad (c1 antes que c2)
    assert chunks_por_entidad[petro.entity_id] == [c1.chunk_id, c2.chunk_id]
    assert chunks_por_entidad[bogota.entity_id] == [c3.chunk_id]


def test_entidades_de_video_sin_menciones_devuelve_vacio(con):
    vrepo, erepo = VideoRepo(con), EntityRepo(con)
    v = _video()
    vrepo.guardar(v)
    entidades, chunks_por_entidad = erepo.catalogo_de_video(v.video_id)
    assert entidades == {}
    assert chunks_por_entidad == {}
