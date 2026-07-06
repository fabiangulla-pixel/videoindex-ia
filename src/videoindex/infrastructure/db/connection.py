"""Conexión SQLite con las garantías del proyecto activadas."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from videoindex.infrastructure.db.migrations import aplicar_migraciones


def conectar(db_path: str | Path) -> sqlite3.Connection:
    """Abre (o crea) la BD con FKs, WAL y esquema al día."""
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    aplicar_migraciones(con)
    return con
