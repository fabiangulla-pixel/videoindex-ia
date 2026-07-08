"""LMStudioProvider: servidor local compatible con la API de OpenAI. Se
mockea urllib (sin depender de un servidor LM Studio real corriendo)."""

import io
import json

from videoindex.infrastructure.llm.providers import LMStudioProvider, modelos_cargados_lmstudio


class _RespuestaFalsa:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode()

    def __enter__(self):
        return io.BytesIO(self._bytes)

    def __exit__(self, *a):
        return False


def test_ask_envia_formato_openai_y_parsea_respuesta(monkeypatch):
    capturado = {}

    def fake_urlopen(peticion, timeout=None):
        capturado["url"] = peticion.full_url
        capturado["payload"] = json.loads(peticion.data)
        return _RespuestaFalsa(
            {
                "choices": [{"message": {"content": "la respuesta del modelo local"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LMStudioProvider(modelo="gemma-3-12b-it-qat")
    texto = provider.ask("system prompt", "user prompt")

    assert texto == "la respuesta del modelo local"
    assert capturado["url"] == "http://localhost:1234/v1/chat/completions"
    assert capturado["payload"]["model"] == "gemma-3-12b-it-qat"
    assert capturado["payload"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert provider.usages() == [{"prompt_tokens": 42, "completion_tokens": 7}]


def test_ask_sin_modelo_explicito_usa_placeholder(monkeypatch):
    capturado = {}

    def fake_urlopen(peticion, timeout=None):
        capturado["payload"] = json.loads(peticion.data)
        return _RespuestaFalsa({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    LMStudioProvider().ask("s", "u")
    assert capturado["payload"]["model"] == "local-model"


def test_modelos_cargados_devuelve_ids(monkeypatch):
    def fake_urlopen(url, timeout=None):
        return _RespuestaFalsa({"data": [{"id": "gemma-3-12b-it-qat"}, {"id": "otro-modelo"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert modelos_cargados_lmstudio() == ["gemma-3-12b-it-qat", "otro-modelo"]


def test_modelos_cargados_servidor_caido_devuelve_vacio(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise OSError("conexión rechazada")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert modelos_cargados_lmstudio() == []
