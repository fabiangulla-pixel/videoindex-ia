"""Lógica pura de hablantes: cruzar turnos de voz con segmentos de texto.

Sin dependencias de infraestructura — no carga modelos, no toca la BD — así
que se testea con datos sintéticos y sirve igual para cualquier
DiarizationProvider (ECAPA local hoy, pyannote u otro mañana).

Dos operaciones distintas, a propósito:
1. `asignar_hablantes`: quién habla en cada segmento de Whisper. Los cortes
   de la diarización y los de Whisper NO coinciden (son dos modelos con
   criterios distintos), así que se resuelve por solapamiento temporal
   máximo, nunca por igualdad de tiempos.
2. `agrupar_intervenciones`: de segmentos ya etiquetados a las
   intervenciones legibles de una transcripción ("MARTA: …"), que es la
   unidad del producto editorial, no el segmento suelto de Whisper.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from videoindex.domain.models import SpeakerTurn, TranscriptSegment

SIN_HABLANTE = "SPEAKER_?"


@dataclass
class Intervencion:
    """Tramo continuo de UN hablante, ya con su texto: la unidad de lectura
    de una transcripción publicable."""

    speaker: str | None
    start_time: float
    end_time: float
    texto: str
    segment_ids: list[str] = field(default_factory=list)


def solapamiento(inicio_a: float, fin_a: float, inicio_b: float, fin_b: float) -> float:
    """Segundos de intersección entre dos intervalos (0 si no se tocan)."""
    return max(0.0, min(fin_a, fin_b) - max(inicio_a, inicio_b))


def asignar_hablantes(
    segmentos: list[TranscriptSegment], turnos: list[SpeakerTurn]
) -> list[TranscriptSegment]:
    """Escribe `speaker` en cada segmento según el turno con el que MÁS se
    solapa. Muta y devuelve la misma lista (igual que el resto del pipeline,
    que trabaja sobre los objetos que va a persistir).

    Un segmento que no solapa con ningún turno hereda el hablante del
    segmento anterior ya etiquetado: en la práctica son interjecciones muy
    cortas dentro de la intervención de alguien, y dejarlas en None partiría
    esa intervención en tres al agrupar. Si no hay anterior (arranque del
    audio), queda None y se muestra como hablante desconocido.
    """
    if not turnos:
        return segmentos
    ordenados = sorted(turnos, key=lambda t: t.start_time)
    ultimo: str | None = None
    for seg in segmentos:
        mejor_solape = 0.0
        mejor_speaker: str | None = None
        for turno in ordenados:
            if turno.start_time >= seg.end_time:
                break  # turnos ordenados: ya no puede haber solapamiento
            solape = solapamiento(seg.start_time, seg.end_time, turno.start_time, turno.end_time)
            if solape > mejor_solape:
                mejor_solape = solape
                mejor_speaker = turno.speaker
        seg.speaker = mejor_speaker if mejor_speaker is not None else ultimo
        if seg.speaker is not None:
            ultimo = seg.speaker
    return segmentos


def turnos_desde_etiquetas(
    regiones: list[tuple[float, float]], etiquetas: list[str | None]
) -> list[SpeakerTurn]:
    """Fusiona regiones consecutivas con la misma etiqueta en turnos.

    Lo usa un provider que clasifica región por región (ECAPA + clustering):
    el contrato del puerto son turnos, no etiquetas sueltas.
    """
    turnos: list[SpeakerTurn] = []
    for (inicio, fin), etiqueta in zip(regiones, etiquetas, strict=True):
        if etiqueta is None:
            continue
        if turnos and turnos[-1].speaker == etiqueta:
            turnos[-1].end_time = max(turnos[-1].end_time, fin)
        else:
            turnos.append(SpeakerTurn(start_time=inicio, end_time=fin, speaker=etiqueta))
    return turnos


def renombrar_por_aparicion(turnos: list[SpeakerTurn]) -> list[SpeakerTurn]:
    """Renumera las etiquetas para que SPEAKER_00 sea el primero en hablar.

    El id de cluster que devuelve un algoritmo de agrupamiento es arbitrario;
    para quien lee la transcripción "SPEAKER_00" debe ser quien abre la
    grabación (casi siempre quien presenta o entrevista).
    """
    mapa: dict[str, str] = {}
    for turno in sorted(turnos, key=lambda t: t.start_time):
        if turno.speaker not in mapa:
            mapa[turno.speaker] = f"SPEAKER_{len(mapa):02d}"
    for turno in turnos:
        turno.speaker = mapa[turno.speaker]
    return turnos


def agrupar_intervenciones(
    segmentos: list[TranscriptSegment],
    pausa_maxima_s: float = 0.0,
    duracion_maxima_s: float = 0.0,
) -> list[Intervencion]:
    """Segmentos consecutivos del MISMO hablante → una intervención.

    `pausa_maxima_s > 0` parte además una intervención cuando hay un silencio
    mayor que ese umbral aunque no cambie el hablante. 0 = no partir por pausa.

    `duracion_maxima_s > 0` parte un turno demasiado largo en párrafos
    manejables. Hace falta de verdad: en un documental, la narración puede
    seguir cinco minutos sin una sola pausa larga, y eso produce un párrafo
    de mil palabras imposible de corregir. El corte cae en una frontera de
    segmento, así que no parte ninguna frase por la mitad, y como el hablante
    es el mismo la atribución no cambia.

    Un video sin diarizar (todos los `speaker` en None) devuelve UNA sola
    intervención sin hablante: la transcripción corrida de siempre.
    """
    intervenciones: list[Intervencion] = []
    for seg in segmentos:
        cortar = True
        if intervenciones:
            previa = intervenciones[-1]
            mismo_hablante = previa.speaker == seg.speaker
            pausa = seg.start_time - previa.end_time
            larga = duracion_maxima_s > 0 and (
                previa.end_time - previa.start_time >= duracion_maxima_s
            )
            cortar = not mismo_hablante or (pausa_maxima_s > 0 and pausa > pausa_maxima_s) or larga
        if cortar:
            intervenciones.append(
                Intervencion(
                    speaker=seg.speaker,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    texto=seg.clean_text,
                    segment_ids=[seg.segment_id],
                )
            )
        else:
            previa = intervenciones[-1]
            previa.end_time = seg.end_time
            previa.texto = f"{previa.texto} {seg.clean_text}".strip()
            previa.segment_ids.append(seg.segment_id)
    return intervenciones


def etiquetas_en_orden(segmentos: list[TranscriptSegment]) -> list[str]:
    """Etiquetas de hablante presentes, en orden de primera aparición."""
    vistas: list[str] = []
    for seg in segmentos:
        if seg.speaker and seg.speaker not in vistas:
            vistas.append(seg.speaker)
    return vistas


def nombre_visible(etiqueta: str | None, nombres: dict[str, str]) -> str:
    """Nombre real si el usuario lo puso; si no, la etiqueta anónima."""
    if etiqueta is None:
        return SIN_HABLANTE
    return nombres.get(etiqueta, etiqueta)
