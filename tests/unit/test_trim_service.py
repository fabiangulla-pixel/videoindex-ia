"""trim_service: nombre del archivo recortado + reemplazo en biblioteca."""

from uuid import uuid4

from videoindex.application.trim_service import generar_ruta_recorte, registrar_recorte
from videoindex.domain.models import Video
from videoindex.infrastructure.db.repositories import ProjectRepo, VideoRepo


def test_generar_ruta_recorte_junto_al_original(tmp_path):
    origen = tmp_path / "clase.mp4"
    origen.write_bytes(b"x")
    assert generar_ruta_recorte(origen) == tmp_path / "clase_recortado.mp4"


def test_generar_ruta_recorte_no_pisa_recortes_previos(tmp_path):
    origen = tmp_path / "clase.mp4"
    origen.write_bytes(b"x")
    (tmp_path / "clase_recortado.mp4").write_bytes(b"y")
    (tmp_path / "clase_recortado_2.mp4").write_bytes(b"z")
    assert generar_ruta_recorte(origen) == tmp_path / "clase_recortado_3.mp4"


def test_registrar_recorte_hereda_proyecto_y_curso(con, tmp_path):
    proyecto = ProjectRepo(con).crear("Seminario X")
    original = Video(
        video_id=str(uuid4()),
        title="clase",
        path=str(tmp_path / "clase.mp4"),
        checksum="ck-original",
        course_name="Agentes IA",
        project_id=proyecto.project_id,
    )
    VideoRepo(con).guardar(original)

    recortada = tmp_path / "clase_recortado.mp4"
    recortada.write_bytes(b"bytes del recorte")  # checksum real; duracion None (no es video)

    nuevo = registrar_recorte(con, original, recortada)

    leido = VideoRepo(con).por_id(nuevo.video_id)
    assert leido is not None
    assert leido.project_id == proyecto.project_id
    assert leido.course_name == "Agentes IA"
    assert leido.processing_status == "pending"  # listo para transcribir
    assert leido.checksum != original.checksum  # identidad propia
    # el original sigue en la biblioteca: quitarlo es decisión del worker
    assert VideoRepo(con).por_id(original.video_id) is not None
