-- VideoIndex IA — esquema v1 (03_Data_Model.md)
-- Reglas: transcripción original inmutable; timestamps absolutos;
-- embeddings versionados (nunca sobrescribir); chunk siempre trazable a video.

CREATE TABLE IF NOT EXISTS videos (
    video_id          TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    path              TEXT NOT NULL,
    checksum          TEXT NOT NULL UNIQUE,
    duration_seconds  REAL,
    course_name       TEXT,
    session_name      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    processing_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending','transcribing','segmenting',
                                     'extracting','indexing','completed','failed')),
    error_message     TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(processing_status);

CREATE TABLE IF NOT EXISTS transcript_segments (
    segment_id  TEXT PRIMARY KEY,
    video_id    TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    start_time  REAL NOT NULL,
    end_time    REAL NOT NULL,
    duration    REAL NOT NULL,
    raw_text    TEXT NOT NULL,
    clean_text  TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_segments_video_time
    ON transcript_segments(video_id, start_time, end_time);

CREATE TABLE IF NOT EXISTS semantic_chunks (
    chunk_id       TEXT PRIMARY KEY,
    video_id       TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    start_time     REAL NOT NULL,
    end_time       REAL NOT NULL,
    full_text      TEXT NOT NULL,
    summary        TEXT,
    discourse_type TEXT NOT NULL DEFAULT 'exposicion'
        CHECK (discourse_type IN ('exposicion','pregunta','ejemplo','definicion','resumen','otro')),
    avg_confidence REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_chunks_video_time
    ON semantic_chunks(video_id, start_time, end_time);

CREATE TABLE IF NOT EXISTS chunk_segments (
    chunk_id   TEXT NOT NULL REFERENCES semantic_chunks(chunk_id) ON DELETE CASCADE,
    segment_id TEXT NOT NULL REFERENCES transcript_segments(segment_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, segment_id)
);

-- FTS5 sincronizada por triggers; unicode61 + remove_diacritics 2 para que
-- "cancion" encuentre "canción" (clave en corpus en español).
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    full_text, summary,
    content='semantic_chunks', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON semantic_chunks BEGIN
    INSERT INTO chunks_fts(rowid, full_text, summary)
    VALUES (new.rowid, new.full_text, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON semantic_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, full_text, summary)
    VALUES ('delete', old.rowid, old.full_text, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON semantic_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, full_text, summary)
    VALUES ('delete', old.rowid, old.full_text, old.summary);
    INSERT INTO chunks_fts(rowid, full_text, summary)
    VALUES (new.rowid, new.full_text, new.summary);
END;

CREATE TABLE IF NOT EXISTS entities (
    entity_id   TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    label_norm  TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    UNIQUE (label_norm, entity_type)
);
CREATE INDEX IF NOT EXISTS idx_entities_norm ON entities(label_norm);

CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id TEXT PRIMARY KEY,
    entity_id  TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    chunk_id   TEXT NOT NULL REFERENCES semantic_chunks(chunk_id) ON DELETE CASCADE,
    video_id   TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    surface    TEXT,
    UNIQUE (entity_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_chunk ON entity_mentions(chunk_id);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id);

-- Knowledge Graph simple del MVP (ADR-005): co-ocurrencia en chunks.
CREATE TABLE IF NOT EXISTS relations (
    relation_id   TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    target_id     TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'co_occurs',
    weight        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (source_id, target_id, relation_type)
);

CREATE TABLE IF NOT EXISTS embedding_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_active  INTEGER NOT NULL DEFAULT 0,
    faiss_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id   TEXT NOT NULL REFERENCES semantic_chunks(chunk_id) ON DELETE CASCADE,
    version_id INTEGER NOT NULL REFERENCES embedding_versions(version_id) ON DELETE CASCADE,
    faiss_id   INTEGER NOT NULL,
    PRIMARY KEY (chunk_id, version_id)
);
CREATE INDEX IF NOT EXISTS idx_chunk_emb_version ON chunk_embeddings(version_id, faiss_id);
