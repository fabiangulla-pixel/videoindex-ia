"""Estándar de costo IA: estimación, cota superior, costo real desde usage."""

from videoindex.infrastructure.llm import costos


def test_estimar_tokens_heuristica():
    assert costos.estimar_tokens("") == 0
    assert costos.estimar_tokens("a" * 400) == 101  # 400/4 + 1


def test_estimacion_modelo_catalogado():
    est = costos.estimar_pregunta_rag(
        "¿qué es un embedding?",
        ["texto de evidencia " * 50],
        "system",
        "gemini",
        "gemini-2.5-flash",
    )
    assert est.modelo_catalogado
    assert est.costo_usd > 0
    assert "COSTO ESTIMADO" in est.resumen()


def test_modelo_desconocido_usa_cota_superior():
    est = costos.estimar_pregunta_rag("q", ["e"], "s", "openai", "gpt-99-turbo-nuevo")
    assert not est.modelo_catalogado
    # cota: el output más caro del catálogo (gpt-5.5, $30/M)
    assert "cota superior" in est.resumen()


def test_ollama_es_gratis():
    est = costos.estimar_pregunta_rag("q", ["e" * 4000], "s", "ollama", "llama3.1")
    assert est.es_local
    assert est.costo_usd == 0.0
    assert "$0" in est.resumen()


def test_costo_real_usages_mixtos():
    usages = [
        {"prompt_tokens": 1000, "completion_tokens": 500},  # OpenAI dict
        {"prompt_token_count": 2000, "candidates_token_count": 300},  # Gemini dict
        None,  # llamada fallida antes del API: se ignora
    ]
    real = costos.costo_real_desde_usages("gemini", "gemini-2.5-flash", usages)
    assert real.tokens_input == 3000
    assert real.tokens_output == 800
    # 3000/1M*0.30 + 800/1M*2.50
    assert abs(real.costo_usd - (0.0009 + 0.002)) < 1e-9


def test_costo_real_objeto_sdk():
    class UsageAnthropicFake:
        input_tokens = 100
        output_tokens = 50

    real = costos.costo_real_desde_usages("claude", "claude-opus-4-8", [UsageAnthropicFake()])
    assert real.tokens_input == 100
    assert real.tokens_output == 50
