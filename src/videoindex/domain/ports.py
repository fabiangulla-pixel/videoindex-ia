"""Puertos (interfaces) del dominio — Dependency Inversion (SAD §3.2).

Las capas superiores dependen de estos Protocols, nunca de implementaciones.
"""

from __future__ import annotations

from typing import Protocol

from videoindex.domain.models import TranscriptSegment


class TranscriptionProvider(Protocol):
    def transcribir(self, ruta_video: str, video_id: str) -> list[TranscriptSegment]:
        """Transcribe el video completo con timestamps absolutos en segundos."""
        ...


class EmbeddingProvider(Protocol):
    def encode(self, textos: list[str]) -> list[list[float]]:
        """Vectores normalizados (norma 1) para producto interno = coseno."""
        ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...


class VectorIndex(Protocol):
    def add(self, ids: list[int], vectores: list[list[float]]) -> None: ...

    def remove(self, ids: list[int]) -> None: ...

    def search(self, vector: list[float], k: int) -> list[tuple[int, float]]:
        """Devuelve [(faiss_id, similitud_coseno), ...] descendente."""
        ...

    def save(self) -> None: ...


class NERProvider(Protocol):
    def extraer(self, texto: str) -> list[tuple[str, str]]:
        """Devuelve [(superficie, tipo), ...]; tipo ∈ persona|lugar|organizacion|otro."""
        ...


class LLMProvider(Protocol):
    def ask(self, system: str, user: str) -> str: ...

    def usages(self) -> list:
        """Objetos usage acumulados, para costo real (estándar de costo IA)."""
        ...

    @property
    def model_name(self) -> str: ...
