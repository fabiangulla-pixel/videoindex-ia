"""Entidades del dominio. Sin dependencias de infraestructura.

Regla de oro (13_Claude_Code_Master_Guide): nunca sacrificar trazabilidad.
Todo timestamp es ABSOLUTO en segundos desde el inicio del video (ADR-002).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Video:
    video_id: str
    title: str
    path: str
    checksum: str
    duration_seconds: float | None = None
    course_name: str | None = None
    session_name: str | None = None
    processing_status: str = "pending"


@dataclass
class TranscriptSegment:
    segment_id: str
    video_id: str
    start_time: float
    end_time: float
    raw_text: str
    clean_text: str
    confidence: float = 0.0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class SemanticChunk:
    """Unidad fundamental del sistema (ADR-001)."""

    chunk_id: str
    video_id: str
    start_time: float
    end_time: float
    full_text: str
    summary: str = ""
    discourse_type: str = "exposicion"
    avg_confidence: float = 0.0
    segment_ids: list[str] = field(default_factory=list)


@dataclass
class Annotation:
    """Nota manual del usuario ligada a un video y un instante ("aquí se
    habla de X"). Independiente del pipeline de IA: se puede anotar
    cualquier video de la biblioteca esté o no transcrito."""

    annotation_id: str
    video_id: str
    timestamp_s: float
    text: str
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Entity:
    entity_id: str
    label: str
    label_norm: str
    entity_type: str


@dataclass
class Evidence:
    """Lo único que el RAG puede entregar al LLM (ADR-003)."""

    chunk_id: str
    video_id: str
    video_title: str
    start_time: float
    end_time: float
    text: str


@dataclass
class ScoreBreakdown:
    semantico: float = 0.0
    textual: float = 0.0
    entidades: float = 0.0
    confianza: float = 0.0


@dataclass
class SearchResult:
    chunk_id: str
    video_id: str
    video_title: str
    video_path: str
    start_time: float
    end_time: float
    snippet: str
    score: float
    breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)


@dataclass
class RAGAnswer:
    text: str
    evidences: list[Evidence]
    cited_indices: list[int]  # índices [n] realmente citados en el texto
    cost_usd: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def anclada(self) -> bool:
        """True si la respuesta cita al menos una evidencia."""
        return bool(self.cited_indices)
