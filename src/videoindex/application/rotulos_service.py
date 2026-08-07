"""Rótulos sobreimpresos: leer quién es quién en la imagen del video.

El OCR de un fotograma suelto es poco fiable — mide sobre este material:
el mismo rótulo se lee "SOLEDAD BIANCHI" (conf 0.92) en un fotograma,
"%LEDAD BIANCHI" en el siguiente y "IANCHI" en el de más allá, según el
fondo que pase por detrás del texto.

La salida se estabiliza con **consenso temporal**: un rótulo real permanece
varios segundos en pantalla, así que se muestrea cada segundo y se elige la
lectura que más se repite. El ruido del OCR (texturas, bordes) casi nunca
produce dos veces exactamente la misma cadena; una palabra real, sí.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Hueco máximo (s) entre dos lecturas para considerarlas el MISMO rótulo.
# Un rótulo parpadea: puede no leerse en 2-3 fotogramas seguidos y volver.
HUECO_MISMO_ROTULO = 6.0
# Un rótulo tiene que leerse al menos dos veces para creérselo.
APARICIONES_MINIMAS = 2


@dataclass
class Rotulo:
    """Un rótulo estabilizado: lo que de verdad estaba escrito en pantalla."""

    inicio_s: float
    fin_s: float
    lineas: list[str] = field(default_factory=list)
    confianza: float = 0.0
    apariciones: int = 0

    @property
    def texto(self) -> str:
        return " / ".join(self.lineas)


def normalizar(texto: str) -> str:
    """Para comparar lecturas: mayúsculas, sin tildes y sin puntuación.

    Los espacios se colapsan al final y no antes: al sustituir la puntuación
    por espacios, "POETA, NOVELISTA" quedaba con dos espacios y entonces
    fallaba la comparación por subcadena contra la misma línea leída sin la
    coma, que es exactamente lo que el consenso necesita detectar.
    """
    nfkd = unicodedata.normalize("NFKD", texto.upper())
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-ZÑ0-9 ]", " ", sin_tildes)).strip()


def detectar_rotulos(
    ruta_video: str | Path,
    cada_s: float = 1.0,
    franja: tuple[float, float] = (0.60, 1.0),
    desde_s: float = 0.0,
    hasta_s: float | None = None,
    progreso: Callable[[float], None] | None = None,
) -> list[Rotulo]:
    """Rótulos estabilizados del video, en orden temporal.

    `franja`: porción vertical donde buscar, en proporción del alto. Por
    defecto el tercio inferior, donde la convención televisiva pone la
    identificación de quien habla.
    """
    from videoindex.infrastructure.media.frames import extraer_fotogramas, recortar_franja
    from videoindex.infrastructure.ocr.tesseract_ocr import leer_lineas

    lecturas: list[tuple[float, str, float, int]] = []  # (t, texto, conf, y)
    for fotograma in extraer_fotogramas(ruta_video, cada_s, desde_s, hasta_s):
        recorte = recortar_franja(fotograma.imagen, *franja)
        for linea in leer_lineas(recorte, fotograma.tiempo_s):
            lecturas.append((fotograma.tiempo_s, linea.texto, linea.confianza, linea.y))
        if progreso and hasta_s:
            progreso(min(1.0, (fotograma.tiempo_s - desde_s) / max(hasta_s - desde_s, 1)))

    return _consenso(lecturas)


def _consenso(lecturas: list[tuple[float, str, float, int]]) -> list[Rotulo]:
    """Agrupa lecturas cercanas en el tiempo y se queda con la mejor variante."""
    if not lecturas:
        return []

    grupos: list[list[tuple[float, str, float, int]]] = [[lecturas[0]]]
    for lectura in lecturas[1:]:
        if lectura[0] - grupos[-1][-1][0] <= HUECO_MISMO_ROTULO:
            grupos[-1].append(lectura)
        else:
            grupos.append([lectura])

    rotulos: list[Rotulo] = []
    for grupo in grupos:
        lineas = _mejores_variantes(grupo)
        if not lineas:
            continue
        rotulos.append(
            Rotulo(
                inicio_s=grupo[0][0],
                fin_s=grupo[-1][0],
                lineas=[texto for texto, _, _ in lineas],
                confianza=sum(conf for _, conf, _ in lineas) / len(lineas),
                apariciones=max(veces for _, _, veces in lineas),
            )
        )
    return rotulos


def _limpiar_bordes(texto: str) -> str:
    """Quita los tokens sueltos de 1-2 caracteres pegados a los extremos.

    Son ruido del OCR que se cuela desde el gráfico del rótulo (medido:
    "TE SOLEDAD BIANCHI" por un adorno a la izquierda del nombre). Solo en
    los bordes: dentro de la línea, un token corto puede ser legítimo
    ("POETA, NOVELISTA Y PERIODISTA").
    """
    tokens = texto.split()
    while tokens and len(tokens[0].strip(".,;:-—|")) <= 2:
        tokens.pop(0)
    while tokens and len(tokens[-1].strip(".,;:-—|")) <= 2:
        tokens.pop()
    return " ".join(tokens)


def _mejores_variantes(grupo: list[tuple[float, str, float, int]]) -> list[tuple[str, float, int]]:
    """De todas las lecturas de un rótulo, las líneas que de verdad estaban.

    Reglas, en este orden:
    1. Las lecturas parciales se agrupan con la completa que las contiene
       ("IANCHI" y "SOLEDAD BIANCHI" son la misma línea leída dos veces).
    2. De cada familia se elige la variante MÁS LARGA y luego se le limpian
       los bordes. Las dos formas de error del OCR piden cosas distintas: la
       lectura parcial es texto que FALTA (y solo la variante larga lo tiene),
       mientras que el ruido del gráfico es texto AÑADIDO y corto en un
       extremo (y eso lo quita _limpiar_bordes). Quedarse con la más repetida
       parecía razonable pero devolvía "ULLOA" en vez de "CARLA ULLOA": lo
       que más se repite es justamente la lectura incompleta.
    3. Se descartan las familias vistas una sola vez.
    """
    variantes: dict[str, dict] = {}
    for _, texto, conf, y in grupo:
        clave = normalizar(texto)
        if not clave:
            continue
        datos = variantes.setdefault(clave, {"texto": texto, "conf": [], "veces": 0, "y": y})
        datos["conf"].append(conf)
        datos["veces"] += 1
        datos["y"] = min(datos["y"], y)

    claves = sorted(variantes, key=len, reverse=True)
    familia: dict[str, list[str]] = {}
    absorbidas: set[str] = set()
    for i, larga in enumerate(claves):
        if larga in absorbidas:
            continue
        familia[larga] = [larga]
        for corta in claves[i + 1 :]:
            if corta not in absorbidas and corta in larga:
                familia[larga].append(corta)
                absorbidas.add(corta)

    resultado: list[tuple[str, float, int]] = []
    posiciones: dict[str, int] = {}
    for miembros in familia.values():
        veces = sum(variantes[c]["veces"] for c in miembros)
        if veces < APARICIONES_MINIMAS:
            continue
        # La lectura más completa de la familia; los bordes se limpian abajo.
        mejor = max(miembros, key=len)
        datos = variantes[mejor]
        texto = _limpiar_bordes(datos["texto"])
        if len(texto) < 3:
            continue
        confianzas = [c for m in miembros for c in variantes[m]["conf"]]
        posiciones[texto] = min(variantes[m]["y"] for m in miembros)
        resultado.append((texto, sum(confianzas) / len(confianzas), veces))

    # De arriba abajo: en un rótulo el nombre va sobre el cargo.
    return sorted(resultado, key=lambda r: posiciones.get(r[0], 0))
