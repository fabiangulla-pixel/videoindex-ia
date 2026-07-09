"""RAG con evidencia obligatoria (principio: evidencia antes que generación).

Contrato duro (ADR-003): el LLM nunca toca la BD. Solo recibe las Evidence que
el Search Engine recuperó. Flujo:
  1. buscar evidencias sobre el umbral — si no hay, NO se llama al LLM ($0, 0 alucinación)
  2. estimar costo → el llamador pide confirmación al usuario
  3. preguntar con prompt estricto de citas [n]
  4. parsear citas y reportar costo real desde usage
"""

from __future__ import annotations

import re

from videoindex.config.settings import RAGSettings
from videoindex.domain.models import Evidence, RAGAnswer
from videoindex.domain.ports import LLMProvider
from videoindex.infrastructure.llm import costos

SYSTEM_PROMPT = (
    "Eres el motor de respuestas de VideoIndex IA. Respondes preguntas sobre un corpus "
    "de videos usando EXCLUSIVAMENTE la evidencia numerada que se te entrega. Reglas:\n"
    "1. Cada afirmación debe llevar su cita [n] correspondiente.\n"
    "2. Si la evidencia no alcanza para responder, dilo explícitamente; NO inventes.\n"
    "3. No uses conocimiento externo al corpus.\n"
    "4. Responde en español, claro y conciso."
)


def _fmt_tiempo(segundos: float) -> str:
    s = int(segundos)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def construir_prompt_usuario(query: str, evidencias: list[Evidence]) -> str:
    bloques = [
        f'[{i}] «{e.video_title}» {_fmt_tiempo(e.start_time)}–{_fmt_tiempo(e.end_time)}: "{e.text}"'
        for i, e in enumerate(evidencias, 1)
    ]
    return "PREGUNTA: " + query + "\n\nEVIDENCIA:\n" + "\n\n".join(bloques)


def parsear_citas(texto: str, n_evidencias: int) -> list[int]:
    """Índices [n] válidos citados en la respuesta, en orden de aparición."""
    vistos: list[int] = []
    for m in re.finditer(r"\[(\d+)\]", texto):
        n = int(m.group(1))
        if 1 <= n <= n_evidencias and n not in vistos:
            vistos.append(n)
    return vistos


class RAGService:
    def __init__(self, search_engine, cfg: RAGSettings | None = None):
        self.search = search_engine
        self.cfg = cfg or RAGSettings()

    def recuperar_evidencias(
        self, query: str, project_id: str | None = "__todos__"
    ) -> list[Evidence]:
        return self.search.evidencias(
            query, self.cfg.k_evidencias, self.cfg.umbral_evidencia, project_id
        )

    def estimar(
        self, query: str, evidencias: list[Evidence], proveedor: str, modelo: str
    ) -> costos.EstimacionCosto:
        return costos.estimar_pregunta_rag(
            query, [e.text for e in evidencias], SYSTEM_PROMPT, proveedor, modelo
        )

    def preguntar(
        self, query: str, evidencias: list[Evidence], llm: LLMProvider, proveedor: str
    ) -> RAGAnswer:
        """Llama al LLM. El llamador ya confirmó el costo (estándar de costo IA)."""
        if not evidencias:
            return RAGAnswer(
                text="No hay evidencia suficiente en tu biblioteca para esta pregunta.",
                evidences=[],
                cited_indices=[],
                cost_usd=0.0,
            )
        texto = llm.ask(SYSTEM_PROMPT, construir_prompt_usuario(query, evidencias))
        real = costos.costo_real_desde_usages(proveedor, llm.model_name, llm.usages())
        return RAGAnswer(
            text=texto,
            evidences=evidencias,
            cited_indices=parsear_citas(texto, len(evidencias)),
            cost_usd=real.costo_usd,
            tokens_in=real.tokens_input,
            tokens_out=real.tokens_output,
        )
