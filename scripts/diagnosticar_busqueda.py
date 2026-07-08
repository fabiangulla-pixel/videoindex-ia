"""Diagnóstico ad-hoc: desglose de scores para una query contra la BD real.
Uso: .venv\\Scripts\\python.exe scripts\\diagnosticar_busqueda.py "datos"
"""

from __future__ import annotations

import sys

from videoindex.config import paths
from videoindex.config.settings import SETTINGS
from videoindex.infrastructure.db.connection import conectar
from videoindex.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider
from videoindex.infrastructure.ner.spacy_ner_provider import SpacyNERProvider
from videoindex.infrastructure.vector.faiss_index import FaissIndex


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "datos"
    con = conectar(paths.DB_PATH)
    embedder = LocalEmbeddingProvider()
    ner = SpacyNERProvider()
    faiss = FaissIndex(paths.FAISS_DIR / "v1.faiss", embedder.dimensions)

    from videoindex.domain.fusion import PesosFusion, fusionar
    from videoindex.infrastructure.db.repositories import (
        ChunkRepo,
        EmbeddingRepo,
        EntityRepo,
        normalizar_label,
    )

    n = SETTINGS.search.candidatos_por_fuente
    row = con.execute("SELECT version_id FROM embedding_versions WHERE is_active = 1").fetchone()

    semanticos = {}
    if row:
        vector = embedder.encode([query])[0]
        hits = faiss.search(vector, n)
        mapa = EmbeddingRepo(con).chunk_por_faiss_id(row["version_id"], [h[0] for h in hits])
        semanticos = {mapa[fid]: sim for fid, sim in hits if fid in mapa}

    textuales = ChunkRepo(con).buscar_fts(query, n)
    candidatos = list(set(semanticos) | set(textuales))
    print(
        f"query={query!r}  candidatos semanticos={len(semanticos)}  textuales={len(textuales)}  union={len(candidatos)}\n"
    )

    ent_query = {s for s, _ in ner.extraer(query)}
    print(f"entidades detectadas en la query: {ent_query}\n")
    ent_query_norm = {normalizar_label(s) for s in ent_query}
    entidades_score = {}
    if ent_query_norm:
        por_chunk = EntityRepo(con).entidades_por_chunks(candidatos)
        for cid, ents in por_chunk.items():
            entidades_score[cid] = len(ent_query_norm & ents) / len(ent_query_norm)

    confianzas = ChunkRepo(con).confianzas(candidatos)
    pesos = PesosFusion(
        semantico=SETTINGS.search.peso_semantico,
        textual=SETTINGS.search.peso_textual,
        entidades=SETTINGS.search.peso_entidades,
        confianza=SETTINGS.search.peso_confianza,
    )
    print(f"pesos: {pesos}\n")
    fusionados = fusionar(semanticos, textuales, entidades_score, confianzas, pesos)[:15]

    filas = {r["chunk_id"]: r for r in ChunkRepo(con).por_ids([cid for cid, _, _ in fusionados])}
    for cid, score, breakdown in fusionados:
        fila = filas.get(cid)
        if not fila:
            continue
        texto = fila["full_text"][:90].replace("\n", " ")
        sem = semanticos.get(cid, 0.0)
        txt_raw = textuales.get(cid)
        print(
            f"score={score:.3f}  sem_raw={sem:.3f} sem_norm={breakdown.semantico:.3f}  "
            f"txt_raw={txt_raw!r} txt_norm={breakdown.textual:.3f}  "
            f"ent={breakdown.entidades:.3f}  conf={breakdown.confianza:.3f}"
        )
        print(f"    [{fila['video_title']} {fila['start_time']:.0f}s] {texto}")

    con.close()


if __name__ == "__main__":
    main()
