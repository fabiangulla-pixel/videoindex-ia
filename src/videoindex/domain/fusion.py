"""Fusión híbrida de rankings — el único bloque sin implementación previa.

Combina las cuatro señales de la spec (04_AI_Architecture Parte 3):
    score = 0.45·semántico + 0.30·textual + 0.15·entidades + 0.10·confianza

Problema real: BM25 de SQLite es negativo (menor = mejor) y su escala depende
del corpus; el coseno vive en ~[0,1]. Normalizamos min-max POR CONSULTA dentro
del conjunto de candidatos, de modo que ambas fuentes queden en [0,1].
Un chunk ausente en una fuente aporta 0 en esa componente.
"""

from __future__ import annotations

from dataclasses import dataclass

from videoindex.domain.models import ScoreBreakdown


@dataclass(frozen=True)
class PesosFusion:
    semantico: float = 0.45
    textual: float = 0.30
    entidades: float = 0.15
    confianza: float = 0.10


def normalizar_minmax(scores: dict[str, float], invertir: bool = False) -> dict[str, float]:
    """Lleva los scores a [0,1] por consulta. Con `invertir`, menor = mejor (BM25).

    Si todos los valores son iguales (incluido un solo candidato), todos valen 1.0:
    estar en el top de una fuente es señal positiva, no neutra.
    """
    if not scores:
        return {}
    vals = scores.values()
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return dict.fromkeys(scores, 1.0)
    rango = hi - lo
    if invertir:
        return {k: (hi - v) / rango for k, v in scores.items()}
    return {k: (v - lo) / rango for k, v in scores.items()}


def fusionar(
    semanticos: dict[str, float],
    textuales_bm25: dict[str, float],
    entidades: dict[str, float],
    confianzas: dict[str, float],
    pesos: PesosFusion | None = None,
) -> list[tuple[str, float, ScoreBreakdown]]:
    """Fusiona las cuatro señales; devuelve [(chunk_id, score, desglose)] descendente.

    - semanticos: chunk_id -> similitud coseno (ya ~[0,1], se normaliza igual).
    - textuales_bm25: chunk_id -> bm25 crudo de SQLite (negativo, menor = mejor).
    - entidades: chunk_id -> solape [0,1] (|ent_query ∩ ent_chunk| / |ent_query|).
    - confianzas: chunk_id -> avg_confidence del chunk [0,1] (no se normaliza:
      es una propiedad absoluta del chunk, no relativa a la consulta).
    """
    pesos = pesos or PesosFusion()
    sem = normalizar_minmax(semanticos)
    txt = normalizar_minmax(textuales_bm25, invertir=True)

    candidatos = set(sem) | set(txt)
    resultados = []
    for cid in candidatos:
        b = ScoreBreakdown(
            semantico=sem.get(cid, 0.0),
            textual=txt.get(cid, 0.0),
            entidades=entidades.get(cid, 0.0),
            confianza=confianzas.get(cid, 0.0),
        )
        score = (
            pesos.semantico * b.semantico
            + pesos.textual * b.textual
            + pesos.entidades * b.entidades
            + pesos.confianza * b.confianza
        )
        resultados.append((cid, score, b))

    resultados.sort(key=lambda r: r[1], reverse=True)
    return resultados


def fusionar_rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion — referencia de calidad detrás de flag (no default).

    rankings: listas de chunk_ids ordenadas de mejor a peor, una por fuente.
    """
    acumulado: dict[str, float] = {}
    for ranking in rankings:
        for pos, cid in enumerate(ranking):
            acumulado[cid] = acumulado.get(cid, 0.0) + 1.0 / (k + pos + 1)
    return sorted(acumulado.items(), key=lambda r: r[1], reverse=True)
