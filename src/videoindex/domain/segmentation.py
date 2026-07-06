"""Segmentación semántica: de segmentos temporales a Semantic Chunks (ADR-001).

100 % local y $0: no requiere LLM. Lógica pura — los embeddings entran
inyectados como función, así que se testea sin cargar modelos.

Fronteras, en orden de prioridad:
1. Dura: pausa entre segmentos > pausa_frontera_s (el VAD ya quitó silencio,
   un gap grande sugiere cambio de tema) o chunk_max_s alcanzado.
2. Semántica: similitud coseno entre la ventana anterior y la siguiente
   por debajo de umbral_coseno, siempre que el chunk lleve >= chunk_min_s.

El texto NUNCA se modifica (SAD: "No modifica el texto. Solo reorganiza").
"""

from __future__ import annotations

import math
from collections.abc import Callable
from uuid import uuid4

from videoindex.config.settings import SegmentationSettings
from videoindex.domain.models import SemanticChunk, TranscriptSegment

EncodeFn = Callable[[list[str]], list[list[float]]]


def _coseno(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _texto_ventana(segmentos: list[TranscriptSegment]) -> str:
    return " ".join(s.clean_text for s in segmentos)


def segmentar(
    segmentos: list[TranscriptSegment],
    encode: EncodeFn,
    cfg: SegmentationSettings | None = None,
) -> list[SemanticChunk]:
    """Agrupa segmentos consecutivos en Semantic Chunks con timestamps absolutos."""
    cfg = cfg or SegmentationSettings()
    if not segmentos:
        return []

    # Índices donde TERMINA un chunk (inclusive).
    cortes: list[int] = []
    inicio_chunk = 0
    for i in range(len(segmentos) - 1):
        actual, siguiente = segmentos[i], segmentos[i + 1]
        duracion_chunk = actual.end_time - segmentos[inicio_chunk].start_time

        if duracion_chunk >= cfg.chunk_max_s:
            cortes.append(i)
            inicio_chunk = i + 1
            continue

        pausa = siguiente.start_time - actual.end_time
        if pausa > cfg.pausa_frontera_s and duracion_chunk >= cfg.chunk_min_s:
            cortes.append(i)
            inicio_chunk = i + 1
            continue

        if duracion_chunk >= cfg.chunk_min_s:
            v = cfg.ventana_segmentos
            antes = segmentos[max(inicio_chunk, i - v + 1) : i + 1]
            despues = segmentos[i + 1 : i + 1 + v]
            if antes and despues:
                emb = encode([_texto_ventana(antes), _texto_ventana(despues)])
                if _coseno(emb[0], emb[1]) < cfg.umbral_coseno:
                    cortes.append(i)
                    inicio_chunk = i + 1

    cortes.append(len(segmentos) - 1)

    chunks: list[SemanticChunk] = []
    inicio = 0
    for fin in cortes:
        grupo = segmentos[inicio : fin + 1]
        if not grupo:
            continue
        confs = [s.confidence for s in grupo]
        chunks.append(
            SemanticChunk(
                chunk_id=str(uuid4()),
                video_id=grupo[0].video_id,
                start_time=grupo[0].start_time,  # absoluto: 1er segmento
                end_time=grupo[-1].end_time,  # absoluto: último segmento
                full_text=_texto_ventana(grupo),
                avg_confidence=sum(confs) / len(confs),
                segment_ids=[s.segment_id for s in grupo],
            )
        )
        inicio = fin + 1
    return chunks


def resumen_local(texto: str, max_keywords: int = 5) -> str:
    """Summary $0: primera oración + palabras clave por frecuencia.

    El resumen con LLM es una acción opcional posterior (con confirmación de
    costo); indexar nunca requiere IA de pago.
    """
    texto = texto.strip()
    if not texto:
        return ""
    for sep in (". ", "? ", "! "):
        idx = texto.find(sep)
        if 20 <= idx <= 200:
            primera = texto[: idx + 1]
            break
    else:
        primera = texto[:200]

    stopwords = {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "en",
        "y",
        "o",
        "que",
        "se",
        "es",
        "por",
        "con",
        "para",
        "no",
        "a",
        "al",
        "lo",
        "su",
        "sus",
        "como",
        "más",
        "pero",
        "este",
        "esta",
        "eso",
        "esto",
        "hay",
        "son",
        "muy",
        "también",
        "entonces",
        "porque",
        "cuando",
        "donde",
        "ya",
    }
    frecuencia: dict[str, int] = {}
    for palabra in texto.lower().split():
        p = palabra.strip(".,;:¿?¡!()\"'")
        if len(p) > 3 and p not in stopwords:
            frecuencia[p] = frecuencia.get(p, 0) + 1
    keywords = [w for w, _ in sorted(frecuencia.items(), key=lambda kv: -kv[1])[:max_keywords]]
    if keywords:
        return f"{primera} [{', '.join(keywords)}]"
    return primera
