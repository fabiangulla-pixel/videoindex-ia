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

# Offset (s) de "inicio real de contenido" detectado por análisis de
# luminancia de video (independiente del VAD de audio). Puramente
# informativo para la UI de reproducción — NO recorta ni desplaza los
# timestamps ya persistidos en transcript_segments/semantic_chunks.
_V3_CONTENT_START = """
ALTER TABLE videos ADD COLUMN content_start_s REAL;
"""

# Proyectos: agrupador real de videos (antes solo existía course_name como
# texto libre sin uso en la GUI). Un video sin proyecto asignado queda con
# project_id NULL ("Sin proyecto"), no se fuerza migrar datos existentes.
_V4_PROYECTOS = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
ALTER TABLE videos ADD COLUMN project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_videos_project ON videos(project_id);
"""

# Hablantes (diarización) + procedencia del material.
#
# - transcript_segments.speaker: etiqueta anónima ("SPEAKER_00") que la
#   diarización asigna a cada segmento. NULL = video sin diarizar (todos los
#   ya procesados antes de esta migración): nada del pipeline lo exige.
# - semantic_chunks.speakers: las etiquetas del chunk como CSV, para no
#   recalcularlas leyendo sus segmentos en cada búsqueda.
# - video_speakers: el nombre REAL que el usuario le pone a cada etiqueta
#   ("SPEAKER_00" → "Marta Ríos"). Por video: la diarización distingue voces
#   dentro de una grabación, no identifica personas entre grabaciones.
# - videos.source_*: de dónde salió el archivo (URL, canal, fecha de
#   publicación) cuando no vino de una carpeta local. Es lo que hace falta
#   para citar la fuente en un producto editorial.
_V5_HABLANTES_Y_PROCEDENCIA = """
ALTER TABLE transcript_segments ADD COLUMN speaker TEXT;
ALTER TABLE semantic_chunks ADD COLUMN speakers TEXT;
ALTER TABLE videos ADD COLUMN source_url TEXT;
ALTER TABLE videos ADD COLUMN source_channel TEXT;
ALTER TABLE videos ADD COLUMN source_published_at TEXT;
CREATE TABLE IF NOT EXISTS video_speakers (
    video_id      TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    speaker_label TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    PRIMARY KEY (video_id, speaker_label)
);
CREATE INDEX IF NOT EXISTS idx_segments_speaker
    ON transcript_segments(video_id, speaker);
"""

# Cada entrada: (versión, SQL). La v1 es el schema.sql completo; futuras
# migraciones se agregan aquí como ALTER/CREATE incrementales.
_MIGRACIONES: list[tuple[int, str]] = [
    (1, _SCHEMA_SQL.read_text(encoding="utf-8")),
    (2, _V2_ANOTACIONES),
    (3, _V3_CONTENT_START),
    (4, _V4_PROYECTOS),
    (5, _V5_HABLANTES_Y_PROCEDENCIA),
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
