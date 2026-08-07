"""Rutas de datos de la aplicación.

Todo lo que la app escribe (BD, índices FAISS, checkpoints) vive bajo DATA_DIR,
fuera del repo (gitignored) y siempre en disco local.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # .exe de PyInstaller: los .py viven empaquetados, no en src/videoindex/.
    # Los datos van junto al ejecutable.
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Permite redirigir los datos (p. ej. en tests) sin tocar código.
DATA_DIR = Path(os.environ.get("VIDEOINDEX_DATA", PROJECT_ROOT / "data"))

DB_PATH = DATA_DIR / "videoindex.db"
FAISS_DIR = DATA_DIR / "faiss"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
# Modelos que una librería copia fuera de su caché de HuggingFace
# (speechbrain necesita un savedir propio).
MODELOS_DIR = DATA_DIR / "modelos"
# Audio/video bajado de una URL. Va bajo DATA_DIR y no en una carpeta
# temporal: el archivo es la fuente de la transcripción y el reproductor
# lo necesita después, no solo durante la ingesta.
DESCARGAS_DIR = DATA_DIR / "descargas"


def ensure_dirs() -> None:
    for d in (DATA_DIR, FAISS_DIR, CHECKPOINT_DIR, MODELOS_DIR, DESCARGAS_DIR):
        d.mkdir(parents=True, exist_ok=True)
