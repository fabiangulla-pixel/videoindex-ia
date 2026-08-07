"""Extracción de fotogramas con PyAV, para leer lo que el video MUESTRA.

En un documental o una entrevista, el nombre de quien habla casi nunca se
dice en voz alta: aparece en un rótulo sobreimpreso (el "generador de
caracteres" o lower third). Sin mirar la imagen, la transcripción se queda
en "SPEAKER_01" para siempre.

Se muestrea cada N segundos en vez de decodificar todo: un rótulo permanece
en pantalla varios segundos, así que un muestreo de 2-3 s no se pierde
ninguno y evita procesar 90.000 fotogramas.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Fotograma:
    tiempo_s: float
    imagen: np.ndarray  # RGB (alto, ancho, 3)


def extraer_fotogramas(
    ruta: str | Path,
    cada_s: float = 2.0,
    desde_s: float = 0.0,
    hasta_s: float | None = None,
) -> Iterator[Fotograma]:
    """Fotogramas muestreados cada `cada_s` segundos, con su instante absoluto.

    Generador a propósito: un documental de una hora a 2 s son ~1800 imágenes
    de 1920x1080; materializarlas todas son varios GB de RAM.
    """
    import av

    with av.open(str(ruta)) as contenedor:
        if not contenedor.streams.video:
            return
        stream = contenedor.streams.video[0]
        stream.thread_type = "AUTO"
        if desde_s > 0:
            contenedor.seek(int(desde_s / stream.time_base), stream=stream)
        siguiente = desde_s
        for frame in contenedor.decode(stream):
            if frame.pts is None:
                continue
            t = float(frame.pts * frame.time_base)
            if hasta_s is not None and t > hasta_s:
                return
            if t + 1e-6 < siguiente:
                continue
            siguiente = t + cada_s
            yield Fotograma(tiempo_s=t, imagen=frame.to_ndarray(format="rgb24"))


def recortar_franja(
    imagen: np.ndarray, desde_alto: float = 0.62, hasta_alto: float = 1.0
) -> np.ndarray:
    """Franja horizontal de la imagen, en proporción de su alto.

    Por defecto el tercio inferior largo (62 %-100 %), que es donde vive el
    rótulo de identificación en la convención televisiva. Recortar antes del
    OCR sube mucho la precisión: el motor deja de leer los carteles del fondo,
    los libros de la estantería y los subtítulos del propio documental.
    """
    alto = imagen.shape[0]
    inicio = max(0, int(alto * desde_alto))
    fin = min(alto, int(alto * hasta_alto))
    return imagen[inicio:fin]
