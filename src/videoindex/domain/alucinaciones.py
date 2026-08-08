"""Detección de texto que Whisper se inventa.

Los modelos de voz alucinan de forma reconocible cuando el audio no tiene
habla: música, silencio, aplausos o los créditos finales. Como se entrenaron
con subtítulos de YouTube, rellenan esos huecos con las coletillas de ese
corpus — "Gracias por ver el video", "Subtítulos realizados por la comunidad
de Amara.org", "¡Suscríbete al canal!" — o repiten la misma frase en bucle.

Caso real de este material: la transcripción de un documental sobre
literatura chilena terminaba con «Gracias por ver el video. Gracias por ver
el video.», atribuido además a Gabriela Mistral.

Criterio: aquí NUNCA se borra nada en silencio. Estas funciones solo
MARCAN; quien las usa decide si excluye el pasaje del texto y lo reporta
como incertidumbre. Un falso positivo que borrase habla real sin avisar
sería peor que la alucinación.
"""

from __future__ import annotations

import re
import unicodedata

# Coletillas de subtítulos de YouTube. Se comparan normalizadas y por
# inclusión: el modelo las produce con variaciones mínimas de puntuación.
FRASES_DE_RELLENO = (
    "gracias por ver el video",
    "gracias por ver este video",
    "gracias por su atencion",
    "suscribete al canal",
    "no olvides suscribirte",
    "subtitulos realizados por la comunidad de amara org",
    "subtitulado por la comunidad de amara org",
    "subtitulos por la comunidad de amara org",
    "mas informacion en www",
    "hasta la proxima",
    "nos vemos en el proximo video",
    "www amara org",
)


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ ]", " ", sin_tildes)).strip()


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto) if f.strip()]


def es_repeticion_en_bucle(texto: str, minimo: int = 2) -> bool:
    """La misma frase repetida seguida, que es como el modelo rellena silencio.

    Se exige que la frase sea corta (menos de 12 palabras): repetir una
    oración larga y compleja es un recurso retórico real de un orador, no un
    fallo del modelo.
    """
    frases = [_normalizar(f) for f in _frases(texto)]
    frases = [f for f in frases if f]
    if len(frases) < minimo:
        return False
    if len(set(frases)) > 1:
        return False
    return len(frases[0].split()) < 12


def es_alucinacion_probable(texto: str) -> bool:
    """True si el pasaje parece generado por el modelo y no dicho por nadie."""
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    if es_repeticion_en_bucle(texto):
        return True
    # Coletilla que ocupa prácticamente todo el pasaje. Se exige que domine el
    # texto (>60 %) para no descartar una intervención real que la mencione
    # de pasada.
    for frase in FRASES_DE_RELLENO:
        if frase in normalizado and len(frase) / len(normalizado) > 0.6:
            return True
    return False
