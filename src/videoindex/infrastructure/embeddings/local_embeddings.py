"""Embeddings locales — adaptado de Bashkar core/embeddings_local.py.

Modelo paraphrase-multilingual-MiniLM-L12-v2: 384 dims, rápido en CPU,
100 % offline tras la descarga inicial (~420 MB en caché HuggingFace).
Migrar a otro modelo = nueva fila en embedding_versions, nunca sobrescribir.
"""

from __future__ import annotations

from functools import lru_cache

MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSIONES = 384


@lru_cache(maxsize=1)
def _modelo():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODELO_EMBEDDINGS)


class LocalEmbeddingProvider:
    @property
    def model_name(self) -> str:
        return MODELO_EMBEDDINGS

    @property
    def dimensions(self) -> int:
        return DIMENSIONES

    def encode(self, textos: list[str]) -> list[list[float]]:
        emb = _modelo().encode(
            textos,
            batch_size=32,
            normalize_embeddings=True,  # norma 1 → producto interno = coseno
            convert_to_numpy=True,
        )
        return emb.astype("float32").tolist()
