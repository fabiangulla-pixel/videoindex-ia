"""modelos_instalados_ollama: descubre qué modelos tiene Ollama descargados
AHORA, en vez de asumir un catálogo fijo (bug real: pedir un modelo no
instalado con 'ollama pull' devuelve 404, no un error de red — el combo
de la GUI mostraba nombres hardcodeados que podían no existir en la
máquina del usuario)."""

import io
import json

from videoindex.infrastructure.llm.providers import modelos_instalados_ollama


class _RespuestaFalsa:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode()

    def __enter__(self):
        return io.BytesIO(self._bytes)

    def __exit__(self, *a):
        return False


def test_modelos_instalados_devuelve_nombres(monkeypatch):
    def fake_urlopen(url, timeout=None):
        return _RespuestaFalsa({"models": [{"name": "gemma4:latest"}, {"name": "gemma3:4b"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert modelos_instalados_ollama() == ["gemma4:latest", "gemma3:4b"]


def test_modelos_instalados_servidor_caido_devuelve_vacio(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise OSError("conexión rechazada")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert modelos_instalados_ollama() == []
