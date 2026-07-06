"""Search Engine — la ÚNICA puerta al conocimiento (ADR-003).

GUI, CLI y RAG consultan aquí; nadie más toca FTS/FAISS/entidades.
score = 0.45·semántico + 0.30·textual + 0.15·entidades + 0.10·confianza
"""

from __future__ import annotations

import sqlite3

from videoindex.config.settings import SearchSettings
from videoindex.domain.fusion import PesosFusion, fusionar
from videoindex.domain.models import Evidence, SearchResult
from videoindex.domain.ports import EmbeddingProvider, NERProvider
from videoindex.infrastructure.db.repositories import (
    ChunkRepo,
    EmbeddingRepo,
    EntityRepo,
    normalizar_label,
)
from videoindex.infrastructure.vector.faiss_index import FaissIndex

_SNIPPET_LARGO = 240


class SearchEngine:
    def __init__(
        self,
        con: sqlite3.Connection,
        embedder: EmbeddingProvider,
        ner: NERProvider,
        faiss_index: FaissIndex,
        settings: SearchSettings | None = None,
    ):
        self.con = con
        self.chunks = ChunkRepo(con)
        self.entidades = EntityRepo(con)
        self.emb_repo = EmbeddingRepo(con)
        self.embedder = embedder
        self.ner = ner
        self.faiss = faiss_index
        self.cfg = settings or SearchSettings()

    def search(self, query: str, k: int = 10) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        n = self.cfg.candidatos_por_fuente

        # Fuente semántica: FAISS sobre la versión de embeddings activa.
        semanticos: dict[str, float] = {}
        row = self.con.execute(
            "SELECT version_id FROM embedding_versions WHERE is_active = 1"
        ).fetchone()
        if row:
            vector = self.embedder.encode([query])[0]
            hits = self.faiss.search(vector, n)
            mapa = self.emb_repo.chunk_por_faiss_id(row["version_id"], [h[0] for h in hits])
            semanticos = {mapa[fid]: sim for fid, sim in hits if fid in mapa}

        # Fuente textual: FTS5/BM25.
        textuales = self.chunks.buscar_fts(query, n)

        candidatos = list(set(semanticos) | set(textuales))
        if not candidatos:
            return []

        # Señal de entidades: solape entre entidades de la query y del chunk.
        ent_query = {normalizar_label(s) for s, _ in self.ner.extraer(query)}
        entidades_score: dict[str, float] = {}
        if ent_query:
            por_chunk = self.entidades.entidades_por_chunks(candidatos)
            for cid, ents in por_chunk.items():
                entidades_score[cid] = len(ent_query & ents) / len(ent_query)

        confianzas = self.chunks.confianzas(candidatos)

        pesos = PesosFusion(
            semantico=self.cfg.peso_semantico,
            textual=self.cfg.peso_textual,
            entidades=self.cfg.peso_entidades,
            confianza=self.cfg.peso_confianza,
        )
        fusionados = fusionar(semanticos, textuales, entidades_score, confianzas, pesos)[:k]

        filas = {r["chunk_id"]: r for r in self.chunks.por_ids([cid for cid, _, _ in fusionados])}
        resultados = []
        for cid, score, breakdown in fusionados:
            fila = filas.get(cid)
            if fila is None:
                continue
            texto = fila["full_text"]
            resultados.append(
                SearchResult(
                    chunk_id=cid,
                    video_id=fila["video_id"],
                    video_title=fila["video_title"],
                    video_path=fila["video_path"],
                    start_time=fila["start_time"],
                    end_time=fila["end_time"],
                    snippet=texto[:_SNIPPET_LARGO] + ("…" if len(texto) > _SNIPPET_LARGO else ""),
                    score=score,
                    breakdown=breakdown,
                )
            )
        return resultados

    def evidencias(self, query: str, k: int, umbral: float) -> list[Evidence]:
        """Para el RAG: solo resultados sobre el umbral, como Evidence."""
        return [
            Evidence(
                chunk_id=r.chunk_id,
                video_id=r.video_id,
                video_title=r.video_title,
                start_time=r.start_time,
                end_time=r.end_time,
                text=self._texto_completo(r.chunk_id),
            )
            for r in self.search(query, k)
            if r.score >= umbral
        ]

    def _texto_completo(self, chunk_id: str) -> str:
        fila = self.chunks.por_ids([chunk_id])
        return fila[0]["full_text"] if fila else ""
