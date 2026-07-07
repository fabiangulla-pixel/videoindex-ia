"""Dossier del video: cobertura completa por entidad, mismo contrato de
evidencia/citas que RAGService, costo agregado sobre N llamadas al LLM."""

from videoindex.application.dossier_service import DossierService
from videoindex.domain.models import Entity, Evidence


class FakeLLMSecuencial:
    """A diferencia del FakeLLM de test_rag.py (una respuesta fija), este
    devuelve una respuesta DISTINTA por llamada, en orden — necesario para
    verificar que las citas de cada entidad se parsean de forma aislada."""

    def __init__(self, respuestas: list[str]):
        self.respuestas = respuestas
        self.llamadas = 0
        self._usages = [{"prompt_tokens": 100, "completion_tokens": 50}] * len(respuestas)

    @property
    def model_name(self) -> str:
        return "gemini-2.5-flash"

    def usages(self):
        return self._usages[: self.llamadas]

    def ask(self, system: str, user: str) -> str:
        texto = self.respuestas[self.llamadas]
        self.llamadas += 1
        return texto


def _entidad(label: str, tipo: str = "persona") -> Entity:
    return Entity(entity_id=label.lower(), label=label, label_norm=label.lower(), entity_type=tipo)


def _evidencia(chunk_id: str, texto: str, inicio: float) -> Evidence:
    return Evidence(
        chunk_id=chunk_id,
        video_id="v1",
        video_title="Clase 1",
        start_time=inicio,
        end_time=inicio + 30,
        text=texto,
    )


def test_generar_llama_llm_una_vez_por_entidad_con_evidencia():
    entidades_evidencia = [
        (_entidad("Petro"), [_evidencia("c1", "Petro dijo X", 0.0)]),
        (_entidad("Bogotá", "lugar"), [_evidencia("c2", "Bogotá se menciona", 30.0)]),
        (_entidad("SinChunks"), []),  # nunca debe generar llamada
    ]
    llm = FakeLLMSecuencial(["resumen de Petro [1]", "resumen de Bogotá [1]"])

    servicio = DossierService.__new__(DossierService)  # no necesita BD para generar()
    dossier, costo_real = servicio.generar(entidades_evidencia, llm, "gemini")

    assert llm.llamadas == 2
    assert len(dossier) == 2
    assert {d.entity_label for d in dossier} == {"Petro", "Bogotá"}


def test_entidad_sin_evidencia_no_genera_llamada():
    entidades_evidencia = [(_entidad("Fantasma"), [])]
    llm = FakeLLMSecuencial([])

    servicio = DossierService.__new__(DossierService)
    dossier, _costo_real = servicio.generar(entidades_evidencia, llm, "gemini")

    assert llm.llamadas == 0
    assert dossier == []


def test_costo_total_agregado_correcto():
    entidades_evidencia = [
        (_entidad("A"), [_evidencia("c1", "texto A", 0.0)]),
        (_entidad("B"), [_evidencia("c2", "texto B", 30.0)]),
    ]
    llm = FakeLLMSecuencial(["resp A [1]", "resp B [1]"])

    servicio = DossierService.__new__(DossierService)
    _dossier, costo_real = servicio.generar(entidades_evidencia, llm, "gemini")

    # 2 llamadas acumuladas: 200 in / 100 out totales (100/50 cada una)
    assert costo_real.tokens_input == 200
    assert costo_real.tokens_output == 100
    assert costo_real.costo_usd > 0


def test_citas_se_parsean_por_entidad_de_forma_aislada():
    entidades_evidencia = [
        (_entidad("A"), [_evidencia("c1", "texto A", 0.0)]),  # 1 evidencia: [9] es inválido
        (_entidad("B"), [_evidencia("c2", "texto B", 30.0)]),  # 1 evidencia: [1] es válido
    ]
    llm = FakeLLMSecuencial(["cita fuera de rango [9]", "cita válida [1]"])

    servicio = DossierService.__new__(DossierService)
    dossier, _costo_real = servicio.generar(entidades_evidencia, llm, "gemini")

    por_label = {d.entity_label: d for d in dossier}
    assert por_label["A"].answer.cited_indices == []  # [9] fuera de rango, descartada
    assert por_label["B"].answer.cited_indices == [1]  # no contaminada por A


def test_exportar_markdown_incluye_citas_y_timestamps():
    entidades_evidencia = [(_entidad("Petro"), [_evidencia("c1", "texto", 185.0)])]
    llm = FakeLLMSecuencial(["Petro habló de economía [1]."])

    servicio = DossierService.__new__(DossierService)
    dossier, _costo_real = servicio.generar(entidades_evidencia, llm, "gemini")
    md = DossierService.exportar_markdown("Clase 1", dossier)

    assert "## Petro (persona)" in md
    assert "[1]" in md
    assert "00:03:05" in md  # 185s absolutos = 00:03:05
