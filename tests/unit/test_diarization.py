"""Lógica pura de hablantes: cruce turnos↔segmentos, turnos e intervenciones.

Sin modelos ni audio: lo que se prueba aquí es la aritmética de intervalos y
las reglas de agrupación, que es donde están los errores caros (una cita
atribuida a quien no la dijo).
"""

from __future__ import annotations

from tests.conftest import hacer_segmentos
from videoindex.domain.diarization import (
    SIN_HABLANTE,
    agrupar_intervenciones,
    asignar_hablantes,
    etiquetas_en_orden,
    nombre_visible,
    renombrar_por_aparicion,
    solapamiento,
    turnos_desde_etiquetas,
)
from videoindex.domain.models import SpeakerTurn


def test_solapamiento_de_intervalos():
    assert solapamiento(0, 10, 5, 15) == 5
    assert solapamiento(0, 10, 10, 20) == 0  # se tocan pero no se solapan
    assert solapamiento(0, 10, 20, 30) == 0
    assert solapamiento(2, 8, 0, 100) == 6  # contenido dentro del otro


def test_asigna_el_hablante_con_mayor_solapamiento():
    """Los cortes de Whisper y los de la diarización no coinciden nunca: el
    segmento se le atribuye a quien más tiempo habla dentro de él."""
    segmentos = hacer_segmentos("v1", [("hola", 0.0, 10.0)])
    turnos = [
        SpeakerTurn(0.0, 3.0, "SPEAKER_00"),
        SpeakerTurn(3.0, 10.0, "SPEAKER_01"),  # 7 s > 3 s
    ]
    asignar_hablantes(segmentos, turnos)
    assert segmentos[0].speaker == "SPEAKER_01"


def test_segmento_sin_turno_hereda_del_anterior():
    """Una interjección corta fuera de todo turno no debe partir en tres la
    intervención de quien está hablando."""
    segmentos = hacer_segmentos("v1", [("uno", 0.0, 5.0), ("ajá", 20.0, 20.4), ("dos", 30.0, 35.0)])
    turnos = [SpeakerTurn(0.0, 5.0, "SPEAKER_00"), SpeakerTurn(30.0, 35.0, "SPEAKER_00")]
    asignar_hablantes(segmentos, turnos)
    assert [s.speaker for s in segmentos] == ["SPEAKER_00"] * 3


def test_segmento_inicial_sin_turno_queda_sin_hablante():
    segmentos = hacer_segmentos("v1", [("ruido", 0.0, 1.0), ("hola", 10.0, 15.0)])
    asignar_hablantes(segmentos, [SpeakerTurn(10.0, 15.0, "SPEAKER_00")])
    assert segmentos[0].speaker is None
    assert segmentos[1].speaker == "SPEAKER_00"


def test_sin_turnos_no_toca_los_segmentos():
    segmentos = hacer_segmentos("v1", [("hola", 0.0, 5.0)])
    asignar_hablantes(segmentos, [])
    assert segmentos[0].speaker is None


def test_turnos_desde_etiquetas_fusiona_consecutivas():
    regiones = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]
    turnos = turnos_desde_etiquetas(regiones, ["a", "a", "b", "b"])
    assert [(t.start_time, t.end_time, t.speaker) for t in turnos] == [
        (0.0, 2.0, "a"),
        (2.0, 4.0, "b"),
    ]


def test_turnos_desde_etiquetas_ignora_regiones_sin_etiqueta():
    """Una región demasiado corta para embeber (None) no debe partir el turno
    de quien sigue hablando a ambos lados."""
    regiones = [(0.0, 2.0), (2.0, 2.3), (2.3, 5.0)]
    turnos = turnos_desde_etiquetas(regiones, ["a", None, "a"])
    assert len(turnos) == 1
    assert (turnos[0].start_time, turnos[0].end_time) == (0.0, 5.0)


def test_renombrar_por_aparicion_ordena_por_quien_habla_primero():
    """El id de cluster es arbitrario; SPEAKER_00 debe ser quien abre."""
    turnos = [
        SpeakerTurn(10.0, 12.0, "c7"),
        SpeakerTurn(0.0, 5.0, "c3"),
        SpeakerTurn(20.0, 25.0, "c7"),
    ]
    renombrar_por_aparicion(turnos)
    assert [t.speaker for t in turnos] == ["SPEAKER_01", "SPEAKER_00", "SPEAKER_01"]


def test_agrupar_intervenciones_une_segmentos_del_mismo_hablante():
    segmentos = hacer_segmentos(
        "v1", [("Buenos", 0.0, 2.0), ("días.", 2.0, 4.0), ("Gracias.", 4.0, 6.0)]
    )
    for seg, quien in zip(segmentos, ["A", "A", "B"], strict=True):
        seg.speaker = quien
    intervenciones = agrupar_intervenciones(segmentos)
    assert len(intervenciones) == 2
    assert intervenciones[0].texto == "Buenos días."
    assert (intervenciones[0].start_time, intervenciones[0].end_time) == (0.0, 4.0)
    assert len(intervenciones[0].segment_ids) == 2
    assert intervenciones[1].speaker == "B"


def test_agrupar_intervenciones_parte_por_pausa_larga():
    segmentos = hacer_segmentos("v1", [("uno", 0.0, 2.0), ("dos", 400.0, 402.0)])
    for seg in segmentos:
        seg.speaker = "A"
    assert len(agrupar_intervenciones(segmentos, pausa_maxima_s=0)) == 1
    assert len(agrupar_intervenciones(segmentos, pausa_maxima_s=60)) == 2


def test_agrupar_intervenciones_sin_diarizar_devuelve_una_sola():
    segmentos = hacer_segmentos("v1", [("uno", 0.0, 2.0), ("dos", 2.0, 4.0)])
    intervenciones = agrupar_intervenciones(segmentos)
    assert len(intervenciones) == 1
    assert intervenciones[0].speaker is None


def test_etiquetas_en_orden_y_nombre_visible():
    segmentos = hacer_segmentos("v1", [("a", 0, 1), ("b", 1, 2), ("c", 2, 3)])
    for seg, quien in zip(segmentos, ["S1", "S0", "S1"], strict=True):
        seg.speaker = quien
    assert etiquetas_en_orden(segmentos) == ["S1", "S0"]
    assert nombre_visible("S1", {"S1": "Marta"}) == "Marta"
    assert nombre_visible("S1", {}) == "S1"  # sin nombre, la etiqueta cruda
    assert nombre_visible(None, {}) == SIN_HABLANTE
