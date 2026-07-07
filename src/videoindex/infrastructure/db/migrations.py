"""Migraciones versionadas (03_Data_Model §2: migraciones versionadas)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_SQL = Path(__file__).with_name("schema.sql")

# Anotaciones manuales del usuario ligadas a un video y un timestamp
# ("en este video se habla de X"). Independientes del pipeline de IA:
# el usuario anota cualquier video de su biblioteca, ya esté transcrito
# o no, mientras lo reproduce.
_V2_ANOTACIONES = """
CREATE TABLE IF NOT EXISTS video_annotations (
    annotation_id TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    timestamp_s   REAL NOT NULL,
    text          TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_annotations_video
    ON video_annotations(video_id, timestamp_s);
"""

# Cada entrada: (versión, SQL). La v1 es el schema.sql completo; futuras
# migraciones se agregan aquí como ALTER/CREATE incrementales.
_MIGRACIONES: list[tuple[int, str]] = [
    (1, _SCHEMA_SQL.read_text(encoding="utf-8")),
    (2, _V2_ANOTACIONES),
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
