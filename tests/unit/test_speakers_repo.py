"""Persistencia de hablantes y de la procedencia del material (migración v5)."""

from __future__ import annotations

from uuid import uuid4

from tests.conftest import hacer_segmentos
from videoindex.domain.models import SemanticChunk, Video
from videoindex.infrastructure.db.repositories import (
    ChunkRepo,
    SegmentRepo,
    SpeakerRepo,
    VideoRepo,
)


def _video(con, **kwargs) -> Video:
    datos = {
        "video_id": str(uuid4()),
        "title": "Charla",
        "path": "C:/videos/charla.m4a",
        "checksum": uuid4().hex,
    }
    datos.update(kwargs)
    v = Video(**datos)
    VideoRepo(con).guardar(v)
    return v


def test_segmento_guarda_y_recupera_su_hablante(con):
    v = _video(con)
    segs = hacer_segmentos(v.video_id, [("hola", 0.0, 2.0), ("adiós", 2.0, 4.0)])
    segs[0].speaker = "SPEAKER_00"
    # El segundo queda sin etiquetar: mezclar ambos casos es lo normal.
    SegmentRepo(con).guardar_lote(segs)

    recuperados = SegmentRepo(con).por_video(v.video_id)
    assert [s.speaker for s in recuperados] == ["SPEAKER_00", None]


def test_chunk_guarda_sus_hablantes_como_lista(con):
    v = _video(con)
    ChunkRepo(con).guardar_lote(
        [
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=v.video_id,
                start_time=0.0,
                end_time=10.0,
                full_text="texto",
                speakers=["SPEAKER_00", "SPEAKER_01"],
            ),
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=v.video_id,
                start_time=10.0,
                end_time=20.0,
                full_text="otro",
            ),
        ]
    )
    chunks = ChunkRepo(con).por_video(v.video_id)
    assert chunks[0].speakers == ["SPEAKER_00", "SPEAKER_01"]
    assert chunks[1].speakers == []  # sin diarizar → lista vacía, no [""]


def test_renombrar_hablante_y_volver_a_la_etiqueta(con):
    v = _video(con)
    repo = SpeakerRepo(con)
    repo.renombrar(v.video_id, "SPEAKER_00", "  Marta Ríos  ")
    assert repo.nombres(v.video_id) == {"SPEAKER_00": "Marta Ríos"}  # se recorta

    repo.renombrar(v.video_id, "SPEAKER_00", "Marta R.")  # sobrescribe
    assert repo.nombres(v.video_id) == {"SPEAKER_00": "Marta R."}

    repo.renombrar(v.video_id, "SPEAKER_00", "   ")  # vacío = quitar el nombre
    assert repo.nombres(v.video_id) == {}


def test_nombres_no_se_mezclan_entre_videos(con):
    a, b = _video(con), _video(con)
    SpeakerRepo(con).renombrar(a.video_id, "SPEAKER_00", "Marta")
    SpeakerRepo(con).renombrar(b.video_id, "SPEAKER_00", "Julián")
    assert SpeakerRepo(con).nombres(a.video_id) == {"SPEAKER_00": "Marta"}
    assert SpeakerRepo(con).nombres(b.video_id) == {"SPEAKER_00": "Julián"}


def test_etiquetas_detectadas_van_en_orden_de_aparicion(con):
    v = _video(con)
    segs = hacer_segmentos(v.video_id, [("a", 30.0, 32.0), ("b", 0.0, 5.0), ("c", 10.0, 12.0)])
    for seg, quien in zip(segs, ["SPEAKER_01", "SPEAKER_00", "SPEAKER_01"], strict=True):
        seg.speaker = quien
    SegmentRepo(con).guardar_lote(segs)
    assert SpeakerRepo(con).etiquetas_detectadas(v.video_id) == ["SPEAKER_00", "SPEAKER_01"]


def test_procedencia_del_video_ida_y_vuelta(con):
    v = _video(
        con,
        source_url="https://www.youtube.com/watch?v=abc",
        source_channel="Universidad de Chile",
        source_published_at="2026-03-14",
    )
    leido = VideoRepo(con).por_id(v.video_id)
    assert leido.source_url == "https://www.youtube.com/watch?v=abc"
    assert leido.source_channel == "Universidad de Chile"
    assert leido.source_published_at == "2026-03-14"


def test_guardar_sin_procedencia_no_borra_la_existente(con):
    """Re-escanear la carpeta de un archivo que se bajó por URL no puede
    hacerle perder la fuente que hay que citar."""
    v = _video(con, source_url="https://ejemplo.org/charla", source_channel="Canal")
    v.source_url = None
    v.source_channel = None
    v.title = "Charla (renombrada)"
    VideoRepo(con).guardar(v)

    leido = VideoRepo(con).por_id(v.video_id)
    assert leido.source_url == "https://ejemplo.org/charla"
    assert leido.source_channel == "Canal"
    assert leido.title == "Charla (renombrada)"  # lo demás sí se actualiza
