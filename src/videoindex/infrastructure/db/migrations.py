"""Migraciones versionadas (03_Data_Model §2: migraciones versionadas)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_SQL = Path(__file__).with_name("schema.sql")

# Cada entrada: (versión, SQL). La v1 es el schema.sql completo; futuras
# migraciones se agregan aquí como ALTER/CREATE incrementales.
_MIGRACIONES: list[tuple[int, str]] = [
    (1, _SCHEMA_SQL.read_text(encoding="utf-8")),
]


def aplicar_migraciones(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    aplicadas = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}
    for version, sql in _MIGRACIONES:
        if version in aplicadas:
            continue
        con.executescript(sql)
        con.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        con.commit()
