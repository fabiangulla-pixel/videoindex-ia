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
    # Instante (s) detectado como inicio real del contenido (después del
    # negro/silencio inicial de la grabación). Puramente informativo para
    # la UI de reproducción: NUNCA se resta de los timestamps de
    # transcript_segments/semantic_chunks, que siguen absolutos (ADR-002).
    # None = aún no detectado (video previo a esta feature, o pendiente).
    content_start_s: float | None = None
    # None = "Sin proyecto" (videos de antes de esta feature, o sin asignar).
    project_id: str | None = None
    # Procedencia: de dónde salió el archivo cuando NO se escaneó de una
    # carpeta local (descarga de YouTube y similares). Son los datos que un
    # producto editorial necesita para citar la fuente, así que se guardan
    # con el video, no en un log aparte. None = archivo local sin origen web.
    source_url: str | None = None
    source_channel: str | None = None
    source_published_at: str | None = None  # ISO YYYY-MM-DD tal como lo da la fuente


@dataclass
class Project:
    project_id: str
    name: str
    created_at: str = ""


@dataclass
class TranscriptSegment:
    segment_id: str
    video_id: str
    start_time: float
    end_time: float
    raw_text: str
    clean_text: str
    confidence: float = 0.0
    # Etiqueta anónima del hablante ("SPEAKER_00"), asignada por la
    # diarización. None = sin diarizar (videos previos a esta feature, o
    # diarización desactivada/fallida): el resto del pipeline no depende
    # de este campo, solo lo enriquece.
    speaker: str | None = None

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class SpeakerTurn:
    """Tramo continuo de audio atribuido a un mismo hablante, con timestamps
    ABSOLUTOS (ADR-002). Es lo que devuelve un DiarizationProvider, con
    independencia de cómo Whisper haya cortado sus segmentos."""

    start_time: float
    end_time: float
    speaker: str

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class Speaker:
    """Nombre real que el usuario le pone a una etiqueta anónima de la
    diarización ("SPEAKER_00" → "Marta Ríos"). Vive por video: la misma
    persona en otro video vuelve a ser una etiqueta anónima hasta que se
    la nombre allí (la diarización no identifica personas, solo distingue
    voces dentro de una grabación)."""

    video_id: str
    speaker_label: str
    display_name: str


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
    # Etiquetas de hablante presentes en el chunk, en orden de aparición.
    # Vacío = video sin diarizar. Con la diarización activa un chunk suele
    # tener UNA sola (el cambio de hablante es frontera dura de chunk).
    speakers: list[str] = field(default_factory=list)


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


@dataclass
class DossierEntidad:
    """Resumen narrativo de TODO lo dicho sobre una entidad en un video
    (cobertura completa, no un top-k de búsqueda). Reutiliza RAGAnswer sin
    modificarlo: mismo contrato de evidencia y citas [n] que el RAG puntual."""

    entity_id: str
    entity_label: str
    entity_type: str
    answer: RAGAnswer
    chunks_cubiertos: int
