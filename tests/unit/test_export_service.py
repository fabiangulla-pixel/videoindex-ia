"""export_service: corpus JSON por video y por proyecto."""

import json
from uuid import uuid4

from videoindex.application.export_service import (
    corpus_de_video,
    exportar_proyecto_json,
    exportar_video_json,
)
from videoindex.domain.models import Annotation, SemanticChunk, Video
from videoindex.infrastructure.db.repositories import (
    AnnotationRepo,
    ChunkRepo,
    EntityRepo,
    ProjectRepo,
    VideoRepo,
)


def _armar_video(con, titulo="Clase 1", project_id=None, estado="completed") -> str:
    video_id = str(uuid4())
    VideoRepo(con).guardar(
        Video(
            video_id=video_id,
            title=titulo,
            path=f"C:/v/{titulo}.mp4",
            checksum=video_id,
            duration_seconds=120.0,
            project_id=project_id,
        )
    )
    VideoRepo(con).actualizar_estado(video_id, estado)
    chunk = SemanticChunk(
        chunk_id=str(uuid4()),
        video_id=video_id,
        start_time=10.0,
        end_time=40.0,
        full_text="Petro habló del acuerdo",
    )
    ChunkRepo(con).guardar_lote([chunk])
    erepo = EntityRepo(con)
    ent = erepo.upsert("Petro", "persona")
    erepo.registrar_mencion(ent.entity_id, chunk.chunk_id, video_id, "Petro")
    erepo.commit()
    AnnotationRepo(con).guardar(
        Annotation(annotation_id=str(uuid4()), video_id=video_id, timestamp_s=15.0, text="clave")
    )
    return video_id


def test_corpus_de_video_estructura_completa(con):
    proyecto = ProjectRepo(con).crear("Seminario X")
    video_id = _armar_video(con, project_id=proyecto.project_id)

    corpus = corpus_de_video(con, video_id)

    assert corpus["video"]["titulo"] == "Clase 1"
    assert corpus["video"]["proyecto"] == "Seminario X"
    assert len(corpus["chunks"]) == 1
    chunk = corpus["chunks"][0]
    assert chunk["inicio_s"] == 10.0 and chunk["fin_s"] == 40.0
    assert chunk["entidades"] == [{"label": "Petro", "tipo": "persona"}]
    assert corpus["anotaciones_manuales"] == [{"timestamp_s": 15.0, "texto": "clave"}]
    assert corpus["exportado_el"]


def test_exportar_video_json_escribe_utf8(con, tmp_path):
    video_id = _armar_video(con)
    destino = exportar_video_json(con, video_id, tmp_path / "corpus.json")

    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["chunks"][0]["texto"] == "Petro habló del acuerdo"  # sin escapar unicode


def test_exportar_proyecto_solo_completados_del_proyecto(con, tmp_path):
    proyecto = ProjectRepo(con).crear("Seminario X")
    _armar_video(con, "completado", project_id=proyecto.project_id)
    _armar_video(con, "pendiente", project_id=proyecto.project_id, estado="pending")
    _armar_video(con, "de otro proyecto")  # sin proyecto

    escritos = exportar_proyecto_json(con, proyecto.project_id, tmp_path / "corpus")

    assert [p.name for p in escritos] == ["completado.json"]
    assert (tmp_path / "corpus" / "completado.json").exists()
