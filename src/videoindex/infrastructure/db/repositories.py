"""Repositorios: única capa que habla SQL (SAD §11: Whisper→Service→Repository→SQLite)."""

from __future__ import annotations

import sqlite3
import unicodedata
from uuid import uuid4

from videoindex.domain.models import Annotation, Entity, SemanticChunk, TranscriptSegment, Video


def normalizar_label(texto: str) -> str:
    """minúsculas + sin tildes, para matching de entidades ('García' == 'garcia')."""
    nfkd = unicodedata.normalize("NFKD", texto.lower().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


class VideoRepo:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def por_checksum(self, checksum: str) -> Video | None:
        row = self.con.execute("SELECT * FROM videos WHERE checksum = ?", (checksum,)).fetchone()
        return self._a_modelo(row) if row else None

    def por_id(self, video_id: str) -> Video | None:
        row = self.con.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return self._a_modelo(row) if row else None

    def guardar(self, v: Video) -> None:
        self.con.execute(
            """INSERT INTO videos (video_id, title, path, checksum, duration_seconds,
                                   course_name, session_name, processing_status, content_start_s)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(checksum) DO UPDATE SET path=excluded.path, title=excluded.title""",
            (
                v.video_id,
                v.title,
                v.path,
                v.checksum,
                v.duration_seconds,
                v.course_name,
                v.session_name,
                v.processing_status,
                v.content_start_s,
            ),
        )
        self.con.commit()

    def actualizar_estado(self, video_id: str, estado: str, error: str | None = None) -> None:
        self.con.execute(
            "UPDATE videos SET processing_status = ?, error_message = ? WHERE video_id = ?",
            (estado, error, video_id),
        )
        self.con.commit()

    def actualizar_content_start(self, video_id: str, offset_s: float) -> None:
        self.con.execute(
            "UPDATE videos SET content_start_s = ? WHERE video_id = ?",
            (offset_s, video_id),
        )
        self.con.commit()

    def listar(self) -> list[Video]:
        rows = self.con.execute("SELECT * FROM videos ORDER BY created_at").fetchall()
        return [self._a_modelo(r) for r in rows]

    @staticmethod
    def _a_modelo(row: sqlite3.Row) -> Video:
        return Video(
            video_id=row["video_id"],
            title=row["title"],
            path=row["path"],
            checksum=row["checksum"],
            duration_seconds=row["duration_seconds"],
            course_name=row["course_name"],
            session_name=row["session_name"],
            processing_status=row["processing_status"],
            content_start_s=row["content_start_s"],
        )


class SegmentRepo:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def guardar_lote(self, segmentos: list[TranscriptSegment]) -> None:
        self.con.executemany(
            """INSERT INTO transcript_segments
               (segment_id, video_id, start_time, end_time, duration, raw_text, clean_text, confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                (
                    s.segment_id,
                    s.video_id,
                    s.start_time,
                    s.end_time,
                    s.duration,
                    s.raw_text,
                    s.clean_text,
                    s.confidence,
                )
                for s in segmentos
            ],
        )
        self.con.commit()

    def por_video(self, video_id: str) -> list[TranscriptSegment]:
        rows = self.con.execute(
            "SELECT * FROM transcript_segments WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        ).fetchall()
        return [
            TranscriptSegment(
                segment_id=r["segment_id"],
                video_id=r["video_id"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                raw_text=r["raw_text"],
                clean_text=r["clean_text"],
                confidence=r["confidence"],
            )
            for r in rows
        ]

    def borrar_por_video(self, video_id: str) -> None:
        """Solo para re-proceso idempotente. raw_text es inmutable mientras el
        video exista con el mismo checksum; re-procesar lo regenera completo."""
        self.con.execute("DELETE FROM transcript_segments WHERE video_id = ?", (video_id,))
        self.con.commit()


class ChunkRepo:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def guardar_lote(self, chunks: list[SemanticChunk]) -> None:
        for c in chunks:
            self.con.execute(
                """INSERT INTO semantic_chunks
                   (chunk_id, video_id, start_time, end_time, full_text, summary,
                    discourse_type, avg_confidence)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    c.chunk_id,
                    c.video_id,
                    c.start_time,
                    c.end_time,
                    c.full_text,
                    c.summary,
                    c.discourse_type,
                    c.avg_confidence,
                ),
            )
            self.con.executemany(
                "INSERT INTO chunk_segments (chunk_id, segment_id) VALUES (?,?)",
                [(c.chunk_id, sid) for sid in c.segment_ids],
            )
        self.con.commit()

    def por_ids(self, chunk_ids: list[str]) -> list[sqlite3.Row]:
        if not chunk_ids:
            return []
        marcas = ",".join("?" * len(chunk_ids))
        return self.con.execute(
            f"""SELECT c.*, v.title AS video_title, v.path AS video_path
                FROM semantic_chunks c JOIN videos v USING (video_id)
                WHERE c.chunk_id IN ({marcas})""",
            chunk_ids,
        ).fetchall()

    def buscar_fts(self, query: str, k: int) -> dict[str, float]:
        """chunk_id -> bm25 crudo (negativo, menor = mejor). Query saneada.

        Cada término va entre comillas dobles para tratarlo como frase literal
        (evita que operadores de FTS5 como NOT/NEAR/* rompan la consulta).
        Una comilla doble literal dentro del término del usuario se escapa
        duplicándola (regla de FTS5 para cadenas entrecomilladas), si no
        `sqlite3.OperationalError: fts5: syntax error` ante términos como
        `dijo "hola"`.
        """
        terminos = [t for t in query.split() if t.strip()]
        if not terminos:
            return {}
        fts_query = " OR ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terminos)
        rows = self.con.execute(
            """SELECT c.chunk_id, bm25(chunks_fts) AS score
               FROM chunks_fts f JOIN semantic_chunks c ON c.rowid = f.rowid
               WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?""",
            (fts_query, k),
        ).fetchall()
        return {r["chunk_id"]: r["score"] for r in rows}

    def confianzas(self, chunk_ids: list[str]) -> dict[str, float]:
        if not chunk_ids:
            return {}
        marcas = ",".join("?" * len(chunk_ids))
        rows = self.con.execute(
            f"SELECT chunk_id, avg_confidence FROM semantic_chunks WHERE chunk_id IN ({marcas})",
            chunk_ids,
        ).fetchall()
        return {r["chunk_id"]: r["avg_confidence"] for r in rows}

    def borrar_por_video(self, video_id: str) -> list[str]:
        """Devuelve los chunk_ids borrados (para limpiar FAISS)."""
        ids = [
            r["chunk_id"]
            for r in self.con.execute(
                "SELECT chunk_id FROM semantic_chunks WHERE video_id = ?", (video_id,)
            )
        ]
        self.con.execute("DELETE FROM semantic_chunks WHERE video_id = ?", (video_id,))
        self.con.commit()
        return ids

    def por_video(self, video_id: str) -> list[SemanticChunk]:
        """TODOS los chunks del video (no top-k), para el Dossier — cobertura
        completa, no búsqueda. segment_ids queda vacío: no se re-persiste."""
        rows = self.con.execute(
            "SELECT * FROM semantic_chunks WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        ).fetchall()
        return [self._a_modelo(r) for r in rows]

    @staticmethod
    def _a_modelo(row: sqlite3.Row) -> SemanticChunk:
        return SemanticChunk(
            chunk_id=row["chunk_id"],
            video_id=row["video_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            full_text=row["full_text"],
            summary=row["summary"] or "",
            discourse_type=row["discourse_type"],
            avg_confidence=row["avg_confidence"],
        )


class EntityRepo:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def upsert(self, label: str, entity_type: str) -> Entity:
        norm = normalizar_label(label)
        row = self.con.execute(
            "SELECT * FROM entities WHERE label_norm = ? AND entity_type = ?",
            (norm, entity_type),
        ).fetchone()
        if row:
            return Entity(row["entity_id"], row["label"], row["label_norm"], row["entity_type"])
        ent = Entity(str(uuid4()), label, norm, entity_type)
        self.con.execute(
            "INSERT INTO entities (entity_id, label, label_norm, entity_type) VALUES (?,?,?,?)",
            (ent.entity_id, ent.label, ent.label_norm, ent.entity_type),
        )
        return ent

    def registrar_mencion(self, entity_id: str, chunk_id: str, video_id: str, surface: str) -> None:
        self.con.execute(
            """INSERT OR IGNORE INTO entity_mentions
               (mention_id, entity_id, chunk_id, video_id, surface) VALUES (?,?,?,?,?)""",
            (str(uuid4()), entity_id, chunk_id, video_id, surface),
        )

    def entidades_por_chunks(self, chunk_ids: list[str]) -> dict[str, set[str]]:
        """chunk_id -> set de label_norm de sus entidades."""
        if not chunk_ids:
            return {}
        marcas = ",".join("?" * len(chunk_ids))
        rows = self.con.execute(
            f"""SELECT m.chunk_id, e.label_norm
                FROM entity_mentions m JOIN entities e USING (entity_id)
                WHERE m.chunk_id IN ({marcas})""",
            chunk_ids,
        ).fetchall()
        resultado: dict[str, set[str]] = {}
        for r in rows:
            resultado.setdefault(r["chunk_id"], set()).add(r["label_norm"])
        return resultado

    def catalogo_de_video(self, video_id: str) -> tuple[dict[str, Entity], dict[str, list[str]]]:
        """(entity_id -> Entity, entity_id -> chunk_ids en orden temporal) —
        para el Dossier: TODAS las entidades del video con TODOS sus chunks,
        una sola query (evita N+1)."""
        rows = self.con.execute(
            """SELECT e.entity_id, e.label, e.label_norm, e.entity_type, m.chunk_id
               FROM entity_mentions m
               JOIN entities e USING (entity_id)
               JOIN semantic_chunks c USING (chunk_id)
               WHERE m.video_id = ?
               ORDER BY e.label_norm, c.start_time""",
            (video_id,),
        ).fetchall()
        entidades: dict[str, Entity] = {}
        chunks_por_entidad: dict[str, list[str]] = {}
        for r in rows:
            eid = r["entity_id"]
            if eid not in entidades:
                entidades[eid] = Entity(eid, r["label"], r["label_norm"], r["entity_type"])
            chunks_por_entidad.setdefault(eid, []).append(r["chunk_id"])
        return entidades, chunks_por_entidad

    def registrar_coocurrencia(self, entity_a: str, entity_b: str) -> None:
        """KG simple del MVP: UPSERT weight+1 sobre el par ordenado."""
        src, tgt = sorted((entity_a, entity_b))
        self.con.execute(
            """INSERT INTO relations (relation_id, source_id, target_id, relation_type, weight)
               VALUES (?,?,?,'co_occurs',1)
               ON CONFLICT(source_id, target_id, relation_type)
               DO UPDATE SET weight = weight + 1""",
            (str(uuid4()), src, tgt),
        )

    def commit(self) -> None:
        self.con.commit()


class EmbeddingRepo:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def version_activa(self, model_name: str, dimensions: int, faiss_path: str) -> int:
        """Devuelve la versión activa para el modelo; la crea si no existe."""
        row = self.con.execute(
            "SELECT version_id FROM embedding_versions WHERE model_name = ? AND is_active = 1",
            (model_name,),
        ).fetchone()
        if row:
            return row["version_id"]
        self.con.execute("UPDATE embedding_versions SET is_active = 0")
        cur = self.con.execute(
            """INSERT INTO embedding_versions (model_name, dimensions, is_active, faiss_path)
               VALUES (?,?,1,?)""",
            (model_name, dimensions, faiss_path),
        )
        self.con.commit()
        return cur.lastrowid

    def siguiente_faiss_id(self, version_id: int) -> int:
        row = self.con.execute(
            "SELECT COALESCE(MAX(faiss_id), -1) + 1 FROM chunk_embeddings WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        return row[0]

    def mapear(self, version_id: int, pares: list[tuple[str, int]]) -> None:
        self.con.executemany(
            "INSERT INTO chunk_embeddings (chunk_id, version_id, faiss_id) VALUES (?,?,?)",
            [(cid, version_id, fid) for cid, fid in pares],
        )
        self.con.commit()

    def chunk_por_faiss_id(self, version_id: int, faiss_ids: list[int]) -> dict[int, str]:
        if not faiss_ids:
            return {}
        marcas = ",".join("?" * len(faiss_ids))
        rows = self.con.execute(
            f"""SELECT faiss_id, chunk_id FROM chunk_embeddings
                WHERE version_id = ? AND faiss_id IN ({marcas})""",
            [version_id, *faiss_ids],
        ).fetchall()
        return {r["faiss_id"]: r["chunk_id"] for r in rows}

    def faiss_ids_por_chunks(self, version_id: int, chunk_ids: list[str]) -> list[int]:
        if not chunk_ids:
            return []
        marcas = ",".join("?" * len(chunk_ids))
        rows = self.con.execute(
            f"""SELECT faiss_id FROM chunk_embeddings
                WHERE version_id = ? AND chunk_id IN ({marcas})""",
            [version_id, *chunk_ids],
        ).fetchall()
        return [r["faiss_id"] for r in rows]

    def borrar_mapeos(self, version_id: int, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        marcas = ",".join("?" * len(chunk_ids))
        self.con.execute(
            f"DELETE FROM chunk_embeddings WHERE version_id = ? AND chunk_id IN ({marcas})",
            [version_id, *chunk_ids],
        )
        self.con.commit()


class AnnotationRepo:
    """Notas manuales del usuario ligadas a video + timestamp."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def guardar(self, a: Annotation) -> None:
        self.con.execute(
            """INSERT INTO video_annotations
               (annotation_id, video_id, timestamp_s, text) VALUES (?,?,?,?)""",
            (a.annotation_id, a.video_id, a.timestamp_s, a.text),
        )
        self.con.commit()

    def actualizar_texto(self, annotation_id: str, texto: str) -> None:
        self.con.execute(
            """UPDATE video_annotations SET text = ?, updated_at = datetime('now')
               WHERE annotation_id = ?""",
            (texto, annotation_id),
        )
        self.con.commit()

    def eliminar(self, annotation_id: str) -> None:
        self.con.execute("DELETE FROM video_annotations WHERE annotation_id = ?", (annotation_id,))
        self.con.commit()

    def por_video(self, video_id: str) -> list[Annotation]:
        rows = self.con.execute(
            """SELECT * FROM video_annotations
               WHERE video_id = ? ORDER BY timestamp_s""",
            (video_id,),
        ).fetchall()
        return [self._a_modelo(r) for r in rows]

    @staticmethod
    def _a_modelo(row: sqlite3.Row) -> Annotation:
        return Annotation(
            annotation_id=row["annotation_id"],
            video_id=row["video_id"],
            timestamp_s=row["timestamp_s"],
            text=row["text"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
