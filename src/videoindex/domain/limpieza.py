"""Limpieza de lectura de una transcripción: quitar el ruido del habla sin
tocar lo que se dijo.

La frontera es estricta y deliberada. Se permite quitar lo que el hablante no
quiso decir (una vacilación, una palabra repetida por tropiezo) y arreglar
espaciado y puntuación. NO se permite resumir, reordenar, cambiar palabras
por sinónimos ni completar ideas: eso ya no sería una transcripción.

Por eso la lista de muletillas es corta y solo tiene interjecciones sin
contenido. Casos como "o sea" o "digamos" quedan fuera a propósito: muchas
veces articulan el argumento, y borrarlas cambiaría el sentido.
"""

from __future__ import annotations

import re

# Interjecciones de vacilación. No incluye "este", que en español es también
# un demostrativo ("este autor"), ni conectores que pueden tener función.
MULETILLAS = ("eh", "ehh", "ehhh", "em", "emm", "mm", "mmm", "ah", "ehm")

_MULETILLA = re.compile(
    r"(?<![\wáéíóúñ])(?:" + "|".join(MULETILLAS) + r")(?![\wáéíóúñ])\s*[,.]?\s*",
    re.IGNORECASE,
)
# Palabra repetida inmediatamente ("la la casa", "que que"). \1 con frontera
# para no destrozar repeticiones legítimas como "muy muy grande" -> se acepta
# el falso positivo: en habla espontánea casi siempre es un tropiezo.
_REPETIDA = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_ESPACIOS = re.compile(r"\s{2,}")
_ESPACIO_ANTES_PUNTUACION = re.compile(r"\s+([,.;:!?])")
_PUNTUACION_REPETIDA = re.compile(r"([,.;:])\1+")


def limpiar_para_lectura(texto: str) -> str:
    """Versión legible del texto, sin alterar el contenido.

    Idempotente: aplicarla dos veces da lo mismo que aplicarla una.
    """
    limpio = _MULETILLA.sub(" ", texto)
    limpio = _REPETIDA.sub(r"\1", limpio)
    limpio = _ESPACIO_ANTES_PUNTUACION.sub(r"\1", limpio)
    limpio = _PUNTUACION_REPETIDA.sub(r"\1", limpio)
    limpio = _ESPACIOS.sub(" ", limpio).strip()
    limpio = re.sub(r"^[,.;:\s]+", "", limpio)
    if limpio:
        limpio = limpio[0].upper() + limpio[1:]
    return limpio
