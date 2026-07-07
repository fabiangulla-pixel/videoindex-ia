"""Embeddings locales — adaptado de Bashkar core/embeddings_local.py.

Modelo paraphrase-multilingual-MiniLM-L12-v2: 384 dims, rápido en CPU,
100 % offline tras la descarga inicial (~420 MB en caché HuggingFace).
Migrar a otro modelo = nueva fila en embedding_versions, nunca sobrescribir.
"""

from __future__ import annotations

import os
from functools import lru_cache

MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSIONES = 384


@lru_cache(maxsize=1)
def _modelo():
    from sentence_transformers import SentenceTransformer

    try:
        # Con el modelo ya en caché (descarga inicial hecha), evita que la
        # librería intente un HEAD request al Hub para revisar versión: si
        # esa llamada de red falla (firewall, sin internet, .exe sin
        # certificados SSL empaquetados), aborta en vez de usar la caché.
        # Bug real: en el .exe compilado esto tumbaba TODO el pipeline
        # (10/10 videos "fallidos") aunque el modelo ya estaba descargado.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        return SentenceTransformer(MODELO_EMBEDDINGS)
    except Exception:
        # Si no hay caché local todavía, sí necesita red para la primera
        # descarga: reintenta en modo online.
        os.environ.pop("HF_HUB_OFFLINE", None)
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
