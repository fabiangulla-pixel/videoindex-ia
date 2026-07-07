"""IngestService: idempotencia + callback de progreso durante el checksum."""

from videoindex.application.ingest_service import IngestService


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
