"""RAG: gate de evidencia (0 llamadas al LLM), prompt con citas, parseo [n]."""

from videoindex.application.rag_service import (
    RAGService,
    construir_prompt_usuario,
    parsear_citas,
)
from videoindex.config.settings import RAGSettings
from videoindex.domain.models import Evidence


class FakeLLM:
    def __init__(self, respuesta: str):
        self.respuesta = respuesta
        self.llamadas = 0
        self._usages = [{"prompt_tokens": 100, "completion_tokens": 50}]

    @property
    def model_name(self) -> str:
        return "gemini-2.5-flash"

    def usages(self):
        return self._usages

    def ask(self, system: str, user: str) -> str:
        self.llamadas += 1
        return self.respuesta


class FakeSearch:
    def __init__(self, evidencias):
        self._evidencias = evidencias

    def evidencias(self, query, k, umbral):
        return self._evidencias


def _evidencia(i: int) -> Evidence:
    return Evidence(
        chunk_id=f"c{i}",
        video_id="v1",
        video_title=f"Clase {i}",
        start_time=60.0 * i,
        end_time=60.0 * i + 30,
        text=f"contenido {i}",
    )


def test_gate_sin_evidencia_no_llama_llm():
    rag = RAGService(FakeSearch([]), RAGSettings())
    llm = FakeLLM("no debería usarse")
    answer = rag.preguntar("¿qué es X?", [], llm, "gemini")
    assert llm.llamadas == 0
    assert answer.cost_usd == 0.0
    assert "No hay evidencia" in answer.text


def test_respuesta_con_citas_parseadas():
    evidencias = [_evidencia(1), _evidencia(2), _evidencia(3)]
    rag = RAGService(FakeSearch(evidencias), RAGSettings())
    llm = FakeLLM("La regresión se explica en [1] y se ejemplifica en [3].")
    answer = rag.preguntar("¿dónde se explica?", evidencias, llm, "gemini")
    assert llm.llamadas == 1
    assert answer.cited_indices == [1, 3]
    assert answer.anclada
    assert answer.cost_usd > 0


def test_respuesta_sin_citas_marca_no_anclada():
    evidencias = [_evidencia(1)]
    rag = RAGService(FakeSearch(evidencias), RAGSettings())
    llm = FakeLLM("Respuesta genérica sin fuentes.")
    answer = rag.preguntar("pregunta", evidencias, llm, "gemini")
    assert not answer.anclada


def test_parsear_citas_valida_rango():
    # [4] no existe con 3 evidencias; [1] repetida cuenta una vez
    assert parsear_citas("Ver [1], [4] y de nuevo [1] y [2].", 3) == [1, 2]


def test_prompt_incluye_timestamps_y_titulos():
    prompt = construir_prompt_usuario("¿qué es?", [_evidencia(2)])
    assert "PREGUNTA: ¿qué es?" in prompt
    assert "«Clase 2»" in prompt
    assert "00:02:00" in prompt  # timestamp absoluto legible
