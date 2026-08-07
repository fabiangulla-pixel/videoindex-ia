"""Puertos (interfaces) del dominio — Dependency Inversion (SAD §3.2).

Las capas superiores dependen de estos Protocols, nunca de implementaciones.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from videoindex.domain.models import SpeakerTurn, TranscriptSegment


class TranscriptionProvider(Protocol):
    def transcribir(
        self,
        ruta_video: str,
        video_id: str,
        progreso: Callable[[float], None] | None = None,
    ) -> list[TranscriptSegment]:
        """Transcribe el video completo con timestamps absolutos en segundos.
        progreso(fraccion 0..1): avance real dentro de este video, opcional."""
        ...


class DiarizationProvider(Protocol):
    def diarizar(
        self,
        ruta_media: str,
        regiones: list[tuple[float, float]],
        progreso: Callable[[float], None] | None = None,
    ) -> list[SpeakerTurn]:
        """Turnos de habla con timestamps absolutos en segundos.

        `regiones` son los tramos con voz ya detectados (en la práctica, los
        segmentos de Whisper, que ya pasaron por su VAD): permite a una
        implementación barata limitarse a decidir QUIÉN habla en cada tramo
        en vez de resolver también DÓNDE hay voz. Una implementación con VAD
        propio (pyannote) puede ignorarlas y devolver sus propios turnos: el
        contrato es el mismo y quien consume asigna por solapamiento.
        """
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
