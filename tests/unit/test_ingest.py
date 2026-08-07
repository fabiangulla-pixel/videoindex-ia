"""IngestService: idempotencia + callback de progreso durante el checksum."""

from videoindex.application.ingest_service import IngestService
from videoindex.infrastructure.db.repositories import VideoRepo


def _crear_video(carpeta, nombre: str, contenido: bytes = b"contenido de video falso"):
    ruta = carpeta / nombre
    ruta.write_bytes(contenido)
    return ruta


def test_escanear_carpeta_reporta_progreso_por_archivo(con, tmp_path):
    _crear_video(tmp_path, "a.mp4")
    _crear_video(tmp_path, "b.mp4", b"otro contenido")

    llamadas = []
    IngestService(con).escanear_carpeta(
        tmp_path, progreso=lambda i, total, nombre: llamadas.append((i, total, nombre))
    )

    assert len(llamadas) == 2
    assert llamadas[0] == (1, 2, "a.mp4")
    assert llamadas[1] == (2, 2, "b.mp4")


def test_escanear_carpeta_sin_progreso_no_falla(con, tmp_path):
    _crear_video(tmp_path, "solo.mp4")
    resultado = IngestService(con).escanear_carpeta(tmp_path)
    assert len(resultado.nuevos) == 1


def test_escanear_carpeta_idempotente_por_checksum(con, tmp_path):
    _crear_video(tmp_path, "a.mp4", b"mismo contenido")
    r1 = IngestService(con).escanear_carpeta(tmp_path)
    assert len(r1.nuevos) == 1

    # re-escanear la misma carpeta: no debe crear un segundo Video
    r2 = IngestService(con).escanear_carpeta(tmp_path)
    assert len(r2.nuevos) == 0
    assert len(r2.pendientes_previos) == 1


def test_escanear_carpeta_admite_audio_puro_e_ignora_no_multimedia(con, tmp_path):
    _crear_video(tmp_path, "clase.mp3", b"audio falso")
    _crear_video(tmp_path, "apuntes.txt", b"esto no es multimedia")

    resultado = IngestService(con).escanear_carpeta(tmp_path)

    assert len(resultado.nuevos) == 1
    assert resultado.nuevos[0].title == "clase"


def test_escanear_carpeta_asigna_proyecto_a_videos_nuevos(con, tmp_path):
    from videoindex.infrastructure.db.repositories import ProjectRepo

    proyecto = ProjectRepo(con).crear("Seminario X")
    _crear_video(tmp_path, "a.mp4")
    resultado = IngestService(con).escanear_carpeta(tmp_path, project_id=proyecto.project_id)
    assert resultado.nuevos[0].project_id == proyecto.project_id


def test_escanear_carpeta_sin_project_id_deja_video_sin_proyecto(con, tmp_path):
    _crear_video(tmp_path, "a.mp4")
    resultado = IngestService(con).escanear_carpeta(tmp_path)
    assert resultado.nuevos[0].project_id is None


def test_reescanear_adopta_videos_huerfanos_al_proyecto(con, tmp_path):
    """Caso real: mismos archivos (mismo checksum) copiados a otro disco y
    re-escaneados dentro de un proyecto nuevo — antes quedaban con
    project_id NULL e invisibles bajo el filtro del proyecto."""
    from videoindex.infrastructure.db.repositories import ProjectRepo, VideoRepo

    _crear_video(tmp_path, "a.mp4", b"mismo contenido")
    IngestService(con).escanear_carpeta(tmp_path)  # primer escaneo, sin proyecto

    proyecto = ProjectRepo(con).crear("Prueba SSD")
    r2 = IngestService(con).escanear_carpeta(tmp_path, project_id=proyecto.project_id)

    assert len(r2.nuevos) == 0  # sigue siendo el mismo video (checksum)
    video = r2.pendientes_previos[0]
    assert video.project_id == proyecto.project_id
    assert VideoRepo(con).por_id(video.video_id).project_id == proyecto.project_id


def test_reescanear_no_roba_videos_de_otro_proyecto(con, tmp_path):
    from videoindex.infrastructure.db.repositories import ProjectRepo, VideoRepo

    prepo = ProjectRepo(con)
    proyecto_a = prepo.crear("Proyecto A")
    proyecto_b = prepo.crear("Proyecto B")
    _crear_video(tmp_path, "a.mp4", b"mismo contenido")
    IngestService(con).escanear_carpeta(tmp_path, project_id=proyecto_a.project_id)

    r2 = IngestService(con).escanear_carpeta(tmp_path, project_id=proyecto_b.project_id)

    video = r2.pendientes_previos[0]
    assert VideoRepo(con).por_id(video.video_id).project_id == proyecto_a.project_id


def _media(tmp_path, nombre="charla.m4a", **kwargs):
    from videoindex.infrastructure.media.youtube import MediaDescargado

    ruta = tmp_path / nombre
    ruta.write_bytes(b"audio-de-prueba")
    datos = {
        "ruta": ruta,
        "titulo": "Mesa redonda sobre archivos",
        "url": "https://www.youtube.com/watch?v=abc123",
        "canal": "Anales UChile",
        "fecha_publicacion": "2026-05-20",
    }
    datos.update(kwargs)
    return MediaDescargado(**datos)


def test_registrar_descarga_guarda_titulo_real_y_procedencia(con, tmp_path):
    """El título es el del video, no el nombre del archivo: es lo que se cita."""
    resultado = IngestService(con).registrar_descarga(_media(tmp_path))

    assert len(resultado.nuevos) == 1
    video = resultado.nuevos[0]
    assert video.title == "Mesa redonda sobre archivos"
    assert video.source_url == "https://www.youtube.com/watch?v=abc123"
    assert video.source_channel == "Anales UChile"
    assert video.source_published_at == "2026-05-20"


def test_bajar_dos_veces_el_mismo_video_no_lo_duplica(con, tmp_path):
    servicio = IngestService(con)
    servicio.registrar_descarga(_media(tmp_path))
    segunda = servicio.registrar_descarga(_media(tmp_path, nombre="copia.m4a"))

    assert segunda.nuevos == []
    assert len(segunda.pendientes_previos) == 1
    assert len(VideoRepo(con).listar()) == 1


def test_descargar_un_archivo_ya_escaneado_le_anade_la_procedencia(con, tmp_path):
    """Mismo audio que ya estaba como archivo local: no se re-transcribe, pero
    sí se completa de dónde salió (que es lo que falta para poder citarlo)."""
    carpeta = tmp_path / "local"
    carpeta.mkdir()
    (carpeta / "charla.m4a").write_bytes(b"audio-de-prueba")
    servicio = IngestService(con)
    escaneo = servicio.escanear_carpeta(carpeta)
    assert escaneo.nuevos[0].source_url is None

    servicio.registrar_descarga(_media(tmp_path))

    video = VideoRepo(con).por_id(escaneo.nuevos[0].video_id)
    assert video.source_url == "https://www.youtube.com/watch?v=abc123"
    assert video.source_channel == "Anales UChile"
