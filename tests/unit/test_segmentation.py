"""Segmentación semántica con embeddings inyectados (sin modelos)."""

from tests.conftest import FakeEmbeddingProvider, hacer_segmentos
from videoindex.config.settings import SegmentationSettings
from videoindex.domain.segmentation import resumen_local, segmentar


def _cfg(**kwargs):
    base = {
        "pausa_frontera_s": 2.0,
        "umbral_coseno": 0.55,
        "ventana_segmentos": 2,
        "chunk_min_s": 10.0,
        "chunk_max_s": 60.0,
    }
    base.update(kwargs)
    return SegmentationSettings(**base)


def _encode(textos):
    return FakeEmbeddingProvider().encode(textos)


def test_sin_segmentos():
    assert segmentar([], _encode, _cfg()) == []


def test_pausa_larga_crea_frontera():
    segs = hacer_segmentos(
        "v1",
        [
            ("tema uno parte a", 0.0, 6.0),
            ("tema uno parte b", 6.5, 12.0),
            # pausa de 8 s → frontera (chunk lleva 12 s ≥ min 10 s)
            ("tema dos parte a", 20.0, 26.0),
            ("tema dos parte b", 26.5, 32.0),
        ],
    )
    # encode que nunca corta por semántica (vectores idénticos)
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert len(chunks) == 2
    # Timestamps ABSOLUTOS: el chunk 2 empieza donde su primer segmento.
    assert chunks[1].start_time == 20.0
    assert chunks[0].end_time == 12.0


def test_chunk_max_fuerza_corte():
    segs = hacer_segmentos("v1", [(f"seg {i}", i * 30.0, i * 30.0 + 29.0) for i in range(5)])
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg(chunk_max_s=60.0))
    assert len(chunks) >= 2


def test_no_corta_antes_de_min():
    segs = hacer_segmentos(
        "v1",
        [
            ("a", 0.0, 2.0),
            # pausa enorme pero el chunk lleva solo 2 s < min 10 s → no corta
            ("b", 50.0, 52.0),
        ],
    )
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert len(chunks) == 1


def test_traza_segment_ids():
    segs = hacer_segmentos("v1", [("a", 0.0, 5.0), ("b", 5.5, 11.0)])
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert chunks[0].segment_ids == [s.segment_id for s in segs]


def test_avg_confidence():
    segs = hacer_segmentos("v1", [("a", 0.0, 5.0), ("b", 5.5, 11.0)], confidence=0.5)
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert abs(chunks[0].avg_confidence - 0.5) < 1e-9


def test_texto_no_se_modifica():
    segs = hacer_segmentos("v1", [("Hola  mundo", 0.0, 5.0)])
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert "Hola  mundo" in chunks[0].full_text


def test_resumen_local():
    texto = (
        "La regresión logística es un modelo de clasificación. "
        "Se usa cuando la variable dependiente es binaria y queremos "
        "estimar probabilidades con regresión sobre datos etiquetados."
    )
    r = resumen_local(texto)
    assert r.startswith("La regresión logística")
    assert "[" in r  # keywords presentes


def test_resumen_vacio():
    assert resumen_local("") == ""


def test_cambio_de_hablante_corta_el_chunk_aunque_no_llegue_al_minimo():
    """Un chunk que mezcla dos voces atribuye mal las citas: la frontera por
    hablante es dura y no espera a chunk_min_s."""
    segs = hacer_segmentos(
        "v1",
        [
            ("pregunta corta", 0.0, 3.0),
            ("respuesta larga que sigue", 3.0, 8.0),
        ],
    )
    segs[0].speaker = "SPEAKER_00"
    segs[1].speaker = "SPEAKER_01"
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert len(chunks) == 2
    assert chunks[0].speakers == ["SPEAKER_00"]
    assert chunks[1].speakers == ["SPEAKER_01"]


def test_cortar_por_hablante_desactivado_mantiene_un_solo_chunk():
    segs = hacer_segmentos("v1", [("a", 0.0, 3.0), ("b", 3.0, 8.0)])
    segs[0].speaker = "SPEAKER_00"
    segs[1].speaker = "SPEAKER_01"
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg(cortar_por_hablante=False))
    assert len(chunks) == 1
    assert chunks[0].speakers == ["SPEAKER_00", "SPEAKER_01"]  # orden de aparición


def test_video_sin_diarizar_no_cambia_de_comportamiento():
    """Con todos los speaker en None la frontera por hablante nunca dispara:
    los videos ya procesados se segmentan igual que antes."""
    segs = hacer_segmentos("v1", [("a", 0.0, 3.0), ("b", 3.0, 8.0)])
    chunks = segmentar(segs, lambda ts: [[1.0, 0.0]] * len(ts), _cfg())
    assert len(chunks) == 1
    assert chunks[0].speakers == []
