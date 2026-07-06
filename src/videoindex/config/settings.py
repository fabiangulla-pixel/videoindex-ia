"""Parámetros de comportamiento del sistema (calibrables sin tocar la lógica)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TranscriptionSettings:
    modelo: str = "small"  # tiny | base | small | medium | large-v3
    idioma: str = "es"
    compute_type: str = "int8"  # CPU sin GPU: int8 es lo más rápido
    # Whisper en CPU satura los cores: un solo worker para transcribir.
    max_workers: int = 1
    # Factor inicial: horas de proceso por hora de video con `small` en CPU.
    # Se recalibra con el tiempo real medido tras el primer video.
    factor_tiempo_inicial: float = 0.5


@dataclass
class SegmentationSettings:
    pausa_frontera_s: float = 2.0  # gap entre segmentos que marca frontera dura
    umbral_coseno: float = 0.55  # similitud entre ventanas bajo la cual se corta
    ventana_segmentos: int = 4  # tamaño de las ventanas comparadas
    chunk_min_s: float = 30.0
    chunk_max_s: float = 300.0


@dataclass
class SearchSettings:
    # Pesos vinculantes de la spec (04_AI_Architecture Parte 3).
    peso_semantico: float = 0.45
    peso_textual: float = 0.30
    peso_entidades: float = 0.15
    peso_confianza: float = 0.10
    candidatos_por_fuente: int = 50
    usar_rrf: bool = False  # RRF de referencia para tests comparativos
    rrf_k: int = 60


@dataclass
class RAGSettings:
    proveedor: str = "gemini"
    modelo: str = "gemini-2.5-flash"
    k_evidencias: int = 8
    umbral_evidencia: float = 0.25  # bajo esto no se llama al LLM


@dataclass
class Settings:
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    segmentation: SegmentationSettings = field(default_factory=SegmentationSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)


SETTINGS = Settings()
