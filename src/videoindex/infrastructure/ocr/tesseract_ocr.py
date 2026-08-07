"""OCR de rótulos sobreimpresos con Tesseract.

Se llama al binario a través de pytesseract, pero con la ruta resuelta
explícitamente: Tesseract casi nunca está en el PATH en Windows y dentro del
.exe de PyInstaller el PATH heredado es aún menos fiable.

El `tessdata` con español vive bajo `data/modelos/tessdata` (descargable sin
permisos de administrador) en vez de dentro de "C:\\Program Files", donde
escribir exige elevación. TESSDATA_PREFIX se apunta ahí.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_RUTAS_TESSERACT = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path(r"D:\Programas\Tesseract-OCR\tesseract.exe"),
)


class OcrNoDisponible(RuntimeError):
    """Tesseract no está instalado: quien llama decide si es fatal o si
    simplemente se sigue sin evidencia visual."""


@lru_cache(maxsize=1)
def _preparar() -> str:
    import pytesseract

    from videoindex.config import paths

    for ruta in _RUTAS_TESSERACT:
        if ruta.exists():
            pytesseract.pytesseract.tesseract_cmd = str(ruta)
            break
    else:
        from shutil import which

        encontrado = which("tesseract")
        if not encontrado:
            raise OcrNoDisponible(
                "No se encontró tesseract.exe. Instálalo desde "
                "https://github.com/UB-Mannheim/tesseract/wiki para poder leer "
                "los rótulos del video."
            )
        pytesseract.pytesseract.tesseract_cmd = encontrado

    tessdata = paths.MODELOS_DIR / "tessdata"
    if (tessdata / "spa.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
        return "spa"
    log.warning("Sin spa.traineddata: el OCR usará inglés y fallará en tildes y ñ")
    return "eng"


@dataclass
class LineaDetectada:
    tiempo_s: float
    texto: str
    confianza: float
    # Posición vertical dentro del recorte. En un rótulo de dos líneas el
    # nombre va arriba y el cargo abajo: sin la `y` no se puede saber cuál
    # es cuál al reconstruir el rótulo.
    y: int = 0


# Confianza mínima por palabra. Medida sobre este material: en un rótulo real
# las palabras salen con 72-93 y el ruido de las texturas del fondo con 4-66.
# 70 separa limpiamente ambas poblaciones.
CONF_MINIMA = 70.0

_SOLO_LETRAS = re.compile(r"[^\W\d_]", re.UNICODE)


def _token_util(texto: str) -> bool:
    """Descarta los tokens que produce el OCR sobre texturas y bordes.

    En el material real la basura son tokens de 1-2 caracteres hechos de
    guiones, barras y comillas ("—", "|", "/:", "V'1"), mientras que las
    palabras de un rótulo tienen al menos dos letras seguidas o son un año.
    """
    limpio = texto.strip()
    if not limpio:
        return False
    if limpio.isdigit():
        return len(limpio) == 4  # un año; los números sueltos son ruido
    return len(_SOLO_LETRAS.findall(limpio)) >= 2


def leer_lineas(
    imagen: np.ndarray, tiempo_s: float = 0.0, conf_minima: float = CONF_MINIMA
) -> list[LineaDetectada]:
    """Líneas de texto legibles en la imagen, ya filtradas.

    Devuelve LÍNEAS y no un bloque único porque en un rótulo cada línea es un
    dato distinto: arriba el nombre, abajo el cargo y la institución. Unirlas
    perdería justo la estructura que hace falta para identificar a alguien.

    `--psm 6` (bloque de texto uniforme) en vez del modo por defecto, que
    asume una página completa y se pierde con dos líneas sobreimpresas.
    """
    import pytesseract
    from PIL import Image

    idioma = _preparar()
    datos = pytesseract.image_to_data(
        Image.fromarray(imagen),
        lang=idioma,
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )

    por_linea: dict[tuple[int, int], list[tuple[str, float, int]]] = {}
    for palabra, conf, bloque, linea, arriba in zip(
        datos["text"],
        datos["conf"],
        datos["block_num"],
        datos["line_num"],
        datos["top"],
        strict=True,
    ):
        valor = float(conf)
        if valor >= conf_minima and _token_util(palabra):
            por_linea.setdefault((bloque, linea), []).append((palabra.strip(), valor, int(arriba)))

    resultado: list[LineaDetectada] = []
    for palabras in por_linea.values():
        texto = re.sub(r"\s+", " ", " ".join(p for p, _, _ in palabras)).strip()
        if len(texto) < 3:
            continue
        media = sum(c for _, c, _ in palabras) / len(palabras) / 100
        arriba = min(y for _, _, y in palabras)
        resultado.append(LineaDetectada(tiempo_s=tiempo_s, texto=texto, confianza=media, y=arriba))
    return sorted(resultado, key=lambda linea: linea.y)


def disponible() -> bool:
    try:
        _preparar()
        return True
    except Exception:
        return False
