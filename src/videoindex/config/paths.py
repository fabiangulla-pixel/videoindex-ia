"""Rutas de datos de la aplicación.

Todo lo que la app escribe (BD, índices FAISS, checkpoints) vive bajo DATA_DIR,
fuera del repo (gitignored) y siempre en disco local.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Permite redirigir los datos (p. ej. en tests) sin tocar código.
DATA_DIR = Path(os.environ.get("VIDEOINDEX_DATA", PROJECT_ROOT / "data"))

DB_PATH = DATA_DIR / "videoindex.db"
FAISS_DIR = DATA_DIR / "faiss"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"


def ensure_dirs() -> None:
    for d in (DATA_DIR, FAISS_DIR, CHECKPOINT_DIR):
        d.mkdir(parents=True, exist_ok=True)
