"""Índice vectorial FAISS — adaptado de Bashkar core/busqueda_semantica.py.

Cambios sobre el original:
- IndexIDMap2(IndexFlatIP): add_with_ids (procesamiento incremental, OA-05:
  agregar un video nunca reconstruye el índice) y remove_ids (idempotencia:
  re-procesar un video elimina sus vectores viejos primero).
- El mapeo chunk_id ↔ faiss_id vive en SQLite (tabla chunk_embeddings),
  no en un ids.json aparte.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class FaissIndex:
    def __init__(self, ruta: str | Path, dimension: int = 384):
        import faiss

        self.ruta = Path(ruta)
        self.dimension = dimension
        if self.ruta.exists():
            # I/O vía Python: write_index/read_index de FAISS (C++) fallan con
            # rutas Windows que llevan tildes (p. ej. el nombre del usuario).
            datos = np.frombuffer(self.ruta.read_bytes(), dtype="uint8")
            self._indice = faiss.deserialize_index(datos)
        else:
            self._indice = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))

    def add(self, ids: list[int], vectores: list[list[float]]) -> None:
        if not ids:
            return
        emb = np.asarray(vectores, dtype="float32")
        self._indice.add_with_ids(emb, np.asarray(ids, dtype="int64"))

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        import faiss

        selector = faiss.IDSelectorArray(np.asarray(ids, dtype="int64"))
        self._indice.remove_ids(selector)

    def search(self, vector: list[float], k: int) -> list[tuple[int, float]]:
        if self._indice.ntotal == 0:
            return []
        q = np.asarray([vector], dtype="float32")
        k_real = min(k, self._indice.ntotal)
        distancias, indices = self._indice.search(q, k_real)
        return [
            (int(idx), float(dist))
            for dist, idx in zip(distancias[0], indices[0], strict=True)
            if idx >= 0
        ]

    def save(self) -> None:
        import faiss

        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        datos = faiss.serialize_index(self._indice)
        self.ruta.write_bytes(bytes(datos))

    @property
    def ntotal(self) -> int:
        return self._indice.ntotal
