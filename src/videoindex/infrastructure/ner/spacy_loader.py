"""Carga robusta del modelo spaCy español, también en el .exe (PyInstaller).

Copiado de Quac (probado en ejecutables congelados). En desarrollo,
``spacy.load("es_core_news_md")`` funciona porque el modelo es un paquete
instalado; en el .exe los datos quedan bajo ``sys._MEIPASS``. Este loader
prueba ambos caminos.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MODELOS = ("es_core_news_md", "es_core_news_sm", "es_core_news_lg")
_cache = {}


def _rutas_candidatas(nombre: str):
    """Posibles ubicaciones del modelo dentro del .exe (carpeta de datos)."""
    bases = []
    if hasattr(sys, "_MEIPASS"):  # PyInstaller onefile/onedir
        bases.append(Path(sys._MEIPASS))
    bases.append(Path(sys.executable).parent / "_internal")
    bases.append(Path(__file__).parent)
    for base in bases:
        carpeta = base / nombre
        if not carpeta.is_dir():
            continue
        # spaCy guarda los datos en una subcarpeta versionada: nombre-<ver>
        subdirs = sorted(carpeta.glob(f"{nombre}-*"))
        if subdirs:
            yield subdirs[-1]
        if (carpeta / "meta.json").exists() and (carpeta / "config.cfg").exists():
            yield carpeta


def cargar_modelo_es():
    """Devuelve un nlp de spaCy español. Lanza RuntimeError claro si no hay."""
    import spacy

    if "nlp" in _cache:
        return _cache["nlp"]

    for nombre in _MODELOS:
        try:
            _cache["nlp"] = spacy.load(nombre)
            return _cache["nlp"]
        except (OSError, ImportError):
            continue

    for nombre in _MODELOS:
        for ruta in _rutas_candidatas(nombre):
            try:
                _cache["nlp"] = spacy.load(str(ruta))
                return _cache["nlp"]
            except (OSError, ImportError):
                continue

    raise RuntimeError(
        "Falta el modelo spaCy español. En desarrollo instálalo con:\n"
        "  python -m spacy download es_core_news_md"
    )
