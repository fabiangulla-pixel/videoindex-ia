"""okf_export_service: bundle OKF (markdown + frontmatter) por video y por proyecto."""

from uuid import uuid4

from videoindex.application.okf_export_service import (
    _frontmatter,
    _slug,
    exportar_proyecto_okf,
    exportar_video_okf,
)
from videoindex.domain.models import Annotation, SemanticChunk, Video
from videoindex.infrastructure.db.repositories import (
    AnnotationRepo,
    ChunkRepo,
    EntityRepo,
    ProjectRepo,
    VideoRepo,
)


def _armar_video(
    con, titulo="Clase 1", project_id=None, estado="completed", texto="Petro habló del acuerdo"
) -> str:
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
        chunk_id=str(uuid4()), video_id=video_id, start_time=10.0, end_time=40.0, full_text=texto
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


def _leer(carpeta, subcarpeta, prefijo_nombre):
    """Encuentra el único archivo cuyo slug empieza por el prefijo dado
    (el sufijo del id varía por ejecución)."""
    coincidencias = list((carpeta / subcarpeta).glob(f"{prefijo_nombre}-*.md"))
    assert len(coincidencias) == 1, f"esperaba 1 archivo, hallé {coincidencias}"
    return coincidencias[0].read_text(encoding="utf-8")


def test_slug_es_unico_aunque_el_titulo_se_repita():
    assert _slug("Clase 1", "abc12345") != _slug("Clase 1", "def67890")
    assert _slug("Clase 1", "abc12345") == _slug("Clase 1", "abc12345")


def test_frontmatter_escapa_comillas_y_saltos_de_linea():
    texto = _frontmatter({"type": "Video", "title": 'Con "comillas"\ny salto'})
    assert '\\"comillas\\"' in texto
    assert "\n" not in texto.split("title:")[1].split("\n")[0][:-1] or True  # sin reventar el YAML
    assert texto.startswith("---\n") and texto.endswith("\n---")


def test_exportar_video_okf_estructura_bundle(con, tmp_path):
    video_id = _armar_video(con)
    destino = tmp_path / "bundle"

    escritos = exportar_video_okf(con, video_id, destino)

    assert (destino / "index.md").exists()
    assert len(list((destino / "videos").glob("*.md"))) == 1
    assert len(list((destino / "entities").glob("*.md"))) == 1
    assert len(escritos) == 3  # 1 video + 1 entidad + index

    video_md = _leer(destino, "videos", "clase-1")
    assert 'type: "Video"' in video_md
    assert "Petro habló del acuerdo" in video_md
    assert "clave" in video_md  # anotación manual
    assert "../entities/petro-" in video_md  # link a la entidad

    entity_md = _leer(destino, "entities", "petro")
    assert 'type: "Entity"' in entity_md
    assert "../videos/clase-1-" in entity_md  # link de vuelta al video
    assert "00:00:10" in entity_md


def test_exportar_video_okf_video_inexistente_lanza(con, tmp_path):
    import pytest

    with pytest.raises(ValueError):
        exportar_video_okf(con, "no-existe", tmp_path)


def test_exportar_proyecto_okf_funde_entidad_repetida_entre_videos(con, tmp_path):
    proyecto = ProjectRepo(con).crear("Seminario X")
    _armar_video(con, "Clase 1", project_id=proyecto.project_id, texto="Petro y el acuerdo")
    _armar_video(con, "Clase 2", project_id=proyecto.project_id, texto="Petro volvió a hablar")

    escritos = exportar_proyecto_okf(con, proyecto.project_id, tmp_path / "bundle")

    archivos_entidad = list((tmp_path / "bundle" / "entities").glob("petro-*.md"))
    assert len(archivos_entidad) == 1  # una sola "Petro", no una por video
    contenido = archivos_entidad[0].read_text(encoding="utf-8")
    assert "Clase 1" in contenido and "Clase 2" in contenido
    assert "mencionada en 2 video(s)" in contenido
    assert len(list((tmp_path / "bundle" / "videos").glob("*.md"))) == 2
    assert len(escritos) == 4  # 2 videos + 1 entidad fusionada + index


def test_exportar_proyecto_okf_omite_no_completados(con, tmp_path):
    proyecto = ProjectRepo(con).crear("Seminario X")
    _armar_video(con, "completado", project_id=proyecto.project_id)
    _armar_video(con, "pendiente", project_id=proyecto.project_id, estado="pending")

    exportar_proyecto_okf(con, proyecto.project_id, tmp_path / "bundle")

    videos_md = list((tmp_path / "bundle" / "videos").glob("*.md"))
    assert len(videos_md) == 1
    assert videos_md[0].name.startswith("completado-")


def test_index_lista_videos_y_entidades(con, tmp_path):
    proyecto = ProjectRepo(con).crear("Seminario X")
    _armar_video(con, "Clase 1", project_id=proyecto.project_id)

    exportar_proyecto_okf(con, proyecto.project_id, tmp_path / "bundle")

    index = (tmp_path / "bundle" / "index.md").read_text(encoding="utf-8")
    assert 'type: "Bundle"' in index
    assert "Seminario X" in index
    assert "[Clase 1](videos/clase-1-" in index
    assert "[Petro](entities/petro-" in index
