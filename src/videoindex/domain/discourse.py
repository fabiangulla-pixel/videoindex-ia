"""Clasificación heurística de discourse_type — local, $0, degradable.

Si ninguna señal aparece, el chunk queda como 'exposicion' (default seguro).
"""

from __future__ import annotations

import re

_PATRONES: list[tuple[str, re.Pattern[str]]] = [
    (
        "definicion",
        re.compile(r"\b(se define|es decir|significa|se entiende por|definimos?)\b", re.I),
    ),
    (
        "ejemplo",
        re.compile(r"\b(por ejemplo|imaginen|supongamos|pongamos el caso|un caso)\b", re.I),
    ),
    (
        "resumen",
        re.compile(r"\b(en resumen|recapitulando|para cerrar|en síntesis|en conclusión)\b", re.I),
    ),
]


def clasificar(texto: str) -> str:
    # Densidad de interrogación: una clase magistral tiene preguntas sueltas;
    # un bloque de diálogo/preguntas concentra varias.
    if texto.count("?") >= 3 or (texto.count("?") >= 1 and len(texto) < 200):
        return "pregunta"
    for tipo, patron in _PATRONES:
        if patron.search(texto):
            return tipo
    return "exposicion"
