"""AnnotationRepo: notas manuales ligadas a video + timestamp."""

from uuid import uuid4

from videoindex.domain.models import Annotation, Video
from videoindex.infrastructure.db.repositories import AnnotationRepo, VideoRepo


def _video(con) -> Video:
    checksum = str(uuid4())  # único por video: guardar() hace UPSERT por checksum
    v = Video(video_id=str(uuid4()), title="Clase 1", path="C:/v/c1.mp4", checksum=checksum)
    VideoRepo(con).guardar(v)
    return v


def test_guardar_y_listar_ordenadas_por_timestamp(con):
    v = _video(con)
    repo = AnnotationRepo(con)
    repo.guardar(
        Annotation(annotation_id=str(uuid4()), video_id=v.video_id, timestamp_s=120.0, text="tarde")
    )
    repo.guardar(
        Annotation(
            annotation_id=str(uuid4()), video_id=v.video_id, timestamp_s=10.0, text="temprano"
        )
    )
    notas = repo.por_video(v.video_id)
    assert [n.text for n in notas] == ["temprano", "tarde"]


def test_actualizar_texto(con):
    v = _video(con)
    repo = AnnotationRepo(con)
    nota_id = str(uuid4())
    repo.guardar(Annotation(annotation_id=nota_id, video_id=v.video_id, timestamp_s=5.0, text="v1"))
    repo.actualizar_texto(nota_id, "v2 corregido")
    notas = repo.por_video(v.video_id)
    assert notas[0].text == "v2 corregido"


def test_eliminar(con):
    v = _video(con)
    repo = AnnotationRepo(con)
    nota_id = str(uuid4())
    repo.guardar(Annotation(annotation_id=nota_id, video_id=v.video_id, timestamp_s=5.0, text="x"))
    repo.eliminar(nota_id)
    assert repo.por_video(v.video_id) == []


def test_notas_de_otro_video_no_se_mezclan(con):
    v1, v2 = _video(con), _video(con)
    repo = AnnotationRepo(con)
    repo.guardar(
        Annotation(annotation_id=str(uuid4()), video_id=v1.video_id, timestamp_s=1.0, text="a")
    )
    repo.guardar(
        Annotation(annotation_id=str(uuid4()), video_id=v2.video_id, timestamp_s=1.0, text="b")
    )
    assert [n.text for n in repo.por_video(v1.video_id)] == ["a"]
    assert [n.text for n in repo.por_video(v2.video_id)] == ["b"]


def test_borrar_video_elimina_sus_notas_en_cascada(con):
    v = _video(con)
    repo = AnnotationRepo(con)
    repo.guardar(
        Annotation(annotation_id=str(uuid4()), video_id=v.video_id, timestamp_s=1.0, text="a")
    )
    con.execute("DELETE FROM videos WHERE video_id = ?", (v.video_id,))
    con.commit()
    assert repo.por_video(v.video_id) == []
