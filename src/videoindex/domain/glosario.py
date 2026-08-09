"""Corrección de nombres propios contra un glosario del propio material.

El error que más caro sale en una transcripción publicable no es la gramática:
son los **nombres propios**. Whisper escribe "Neruda" bien porque es famoso,
pero se inventa la grafía de un apellido poco frecuente, y hay que cazarlo a
mano frase por frase.

El glosario no se escribe a mano: sale del video. Los rótulos sobreimpresos y
las tarjetas de cita traen los nombres CON su ortografía correcta, porque
están escritos en pantalla.

**Dos niveles, y la razón por la que son dos.** Se midieron pares reales:

    corregir      Bolano  → Bolaño        1.000
                  Gabriella → Gabriela    0.941
                  Bianqui → Bianchi       0.714
    NO tocar      Boliviano → Bolaño      0.800   <-- más alto que Bianqui
                  banco → Bianchi         0.667

Las dos clases **se solapan**: ningún umbral de similitud las separa. Así que
se parte en dos:

1. **Automático** solo cuando las formas coinciden letra a letra ignorando
   tildes y mayúsculas. Ahí no se cambia ninguna letra, solo se restauran los
   diacríticos: riesgo cero de convertir una palabra en otra.
2. **Sugerencia** para el resto de parecidos, que van a revisión humana. Se
   exige además que la longitud no difiera en más de dos caracteres, que es
   lo que descarta "Boliviano → Bolaño" sin perder "Bianqui → Bianchi".

Nunca se sustituye una palabra por otra distinta sin que lo apruebe una
persona: en un texto publicado eso sería poner en boca de alguien algo que no
dijo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Similitud mínima para SUGERIR (nunca para corregir sola).
#
# Medido sobre el material real: con 0.70 la lista se llenaba de basura
# ("blanco"→"Bolaño", "camino"→"Canto", "María"→"MYRIAM") y una lista de
# sugerencias falsas no la revisa nadie. Con 0.85 quedan solo las creíbles
# ("Alejandra"→"Alejandro", "Gabriel"→"Gabriela").
SIMILITUD_SUGERENCIA = 0.85
# Diferencia máxima de longitud entre la palabra y el término del glosario.
# Es lo que separa "Bianqui/Bianchi" (0) de "Boliviano/Bolaño" (3).
DIFERENCIA_LARGO_MAXIMA = 2
# Palabras más cortas no se tocan: cambiarles una letra las convierte en otra
# palabra corriente del idioma.
LARGO_MINIMO = 5


@dataclass
class Correccion:
    original: str
    corregido: str
    similitud: float


@dataclass
class ResultadoCorreccion:
    texto: str
    #: Aplicadas: solo restauración de tildes y mayúsculas.
    cambios: list[Correccion] = field(default_factory=list)
    #: Candidatas que requieren ojo humano; NO se han aplicado.
    sugerencias: list[Correccion] = field(default_factory=list)


def _plano(palabra: str) -> str:
    nfkd = unicodedata.normalize("NFKD", palabra.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _plano(a), _plano(b)).ratio()


def _aplicar_caja(termino: str, modelo: str) -> str:
    """Las letras de `termino` con la caja de `modelo`.

    Así "bolano" (minúscula en el audio) recupera la eñe sin volverse
    "Bolaño" ni "BOLAÑO": se arregla la ortografía, no el estilo.
    """
    if modelo.isupper():
        return termino.upper()
    if modelo[:1].isupper():
        return termino[:1].upper() + termino[1:].lower()
    return termino.lower()


def construir_glosario(nombres: list[str], obras: list[str] | None = None) -> list[str]:
    """Términos sueltos a vigilar, sacados de los rótulos del video.

    Los nombres se parten en palabras: en el audio casi nunca se dice el
    nombre completo ("dijo Bianchi", no "dijo Soledad Bianchi"), así que hay
    que poder corregir el apellido por su cuenta.
    """
    terminos: set[str] = set()
    for frase in [*nombres, *(obras or [])]:
        for palabra in re.findall(r"[^\W\d_]+", frase, re.UNICODE):
            if len(palabra) >= LARGO_MINIMO:
                terminos.add(palabra)
    return sorted(terminos)


def corregir(texto: str, glosario: list[str]) -> ResultadoCorreccion:
    """Restaura tildes y mayúsculas de los términos del glosario.

    Solo aplica lo seguro; el resto de parecidos sale en `sugerencias` sin
    tocar el texto. Conserva puntuación y espacios.
    """
    if not glosario:
        return ResultadoCorreccion(texto)

    # Índice por forma sin tildes: ahí es donde "bolano" encuentra "Bolaño".
    por_plano: dict[str, str] = {}
    for termino in glosario:
        por_plano.setdefault(_plano(termino), termino)
    exactos = {t for t in glosario}

    cambios: list[Correccion] = []
    sugerencias: list[Correccion] = []
    vistas_sugeridas: set[tuple[str, str]] = set()

    def reemplazar(match: re.Match) -> str:
        palabra = match.group(0)
        if len(palabra) < LARGO_MINIMO or palabra in exactos:
            return palabra

        plano = _plano(palabra)
        canonico = por_plano.get(plano)
        if canonico is not None:
            # Mismas letras ignorando tildes. Solo se restauran los DIACRÍTICOS;
            # la caja se respeta siempre.
            #
            # Tocar la caja parecía inofensivo y no lo era: los rótulos vienen
            # en mayúsculas y los títulos de libro capitalizados, así que
            # "los detectives salvajes" en prosa corriente se convertía en
            # "los Detectives Salvajes", "en general" en "en General" y
            # "González" en "GONZÁLEZ". Eso no es corregir: es estropear.
            if palabra.lower() == canonico.lower():
                return palabra  # solo difieren en caja: no hay nada que arreglar
            corregido = _aplicar_caja(canonico, palabra)
            if corregido != palabra:
                cambios.append(Correccion(palabra, corregido, 1.0))
                return corregido
            return palabra

        # Solo se sugiere sobre palabras que parecen nombre propio. Sin esto,
        # el grueso de las sugerencias eran palabras corrientes en minúscula
        # ("blanco", "camino", "burlando") que casualmente se parecen a un
        # apellido.
        if not palabra[:1].isupper():
            return palabra

        mejor, puntaje = None, 0.0
        for termino in glosario:
            if abs(len(termino) - len(palabra)) > DIFERENCIA_LARGO_MAXIMA:
                continue
            if _plano(termino)[0] != plano[0]:
                continue
            similitud = _similar(palabra, termino)
            if similitud > puntaje:
                mejor, puntaje = termino, similitud
        if mejor is not None and puntaje >= SIMILITUD_SUGERENCIA:
            clave = (palabra, mejor)
            if clave not in vistas_sugeridas:
                vistas_sugeridas.add(clave)
                sugerencias.append(Correccion(palabra, mejor, puntaje))
        return palabra  # las sugerencias NUNCA se aplican solas

    nuevo = re.sub(r"[^\W\d_]+", reemplazar, texto, flags=re.UNICODE)
    return ResultadoCorreccion(nuevo, cambios, sugerencias)
