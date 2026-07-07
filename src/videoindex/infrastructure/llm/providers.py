"""Proveedores LLM intercambiables (Dependency Inversion, OA-04).

Cada provider implementa el puerto LLMProvider: ask(system, user) -> str y
usages() para el costo real. Las API keys se buscan primero en el Windows
Credential Manager (guardadas desde el diálogo de Configuración de la GUI,
ver infrastructure/llm/secrets.py) y, si no hay ninguna ahí, en la variable
de entorno correspondiente (GEMINI_API_KEY / OPENAI_API_KEY /
ANTHROPIC_API_KEY) — esto mantiene compatible el uso por CLI/tests sin
depender de la GUI. Ollama no necesita key.

Los SDK se importan de forma tardía: solo paga la importación quien usa el
proveedor, y el .exe no requiere tenerlos todos instalados.
"""

from __future__ import annotations

import os

from videoindex.infrastructure.llm.secrets import load_api_key


class ProveedorNoConfigurado(RuntimeError):
    pass


def _key(nombre_env: str, proveedor_id: str, nombre_legible: str) -> str:
    key = load_api_key(proveedor_id)
    if not key:
        key = os.environ.get(nombre_env, "").strip()
    if not key:
        raise ProveedorNoConfigurado(
            f"Falta la API key de {nombre_legible}: configúrala en "
            f"Configuración → API Keys, o define la variable de entorno {nombre_env}."
        )
    return key


class GeminiProvider:
    def __init__(self, modelo: str = "gemini-2.5-flash"):
        self._modelo = modelo
        self._usages: list = []

    @property
    def model_name(self) -> str:
        return self._modelo

    def usages(self) -> list:
        return self._usages

    def ask(self, system: str, user: str) -> str:
        from google import genai

        client = genai.Client(api_key=_key("GEMINI_API_KEY", "gemini", "Gemini"))
        respuesta = client.models.generate_content(
            model=self._modelo,
            contents=user,
            config={"system_instruction": system},
        )
        if respuesta.usage_metadata:
            self._usages.append(
                {
                    "prompt_token_count": respuesta.usage_metadata.prompt_token_count,
                    "candidates_token_count": respuesta.usage_metadata.candidates_token_count,
                }
            )
        return respuesta.text or ""


class OpenAIProvider:
    def __init__(self, modelo: str = "gpt-5.4-mini"):
        self._modelo = modelo
        self._usages: list = []

    @property
    def model_name(self) -> str:
        return self._modelo

    def usages(self) -> list:
        return self._usages

    def ask(self, system: str, user: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=_key("OPENAI_API_KEY", "openai", "OpenAI"))
        respuesta = client.chat.completions.create(
            model=self._modelo,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        if respuesta.usage:
            self._usages.append(respuesta.usage)
        return respuesta.choices[0].message.content or ""


class ClaudeProvider:
    def __init__(self, modelo: str = "claude-opus-4-8"):
        self._modelo = modelo
        self._usages: list = []

    @property
    def model_name(self) -> str:
        return self._modelo

    def usages(self) -> list:
        return self._usages

    def ask(self, system: str, user: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY", "claude", "Claude"))
        respuesta = client.messages.create(
            model=self._modelo,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if respuesta.usage:
            self._usages.append(respuesta.usage)
        return next((b.text for b in respuesta.content if b.type == "text"), "")


class OllamaProvider:
    """Modelo local, costo $0. Requiere el servidor de Ollama corriendo."""

    def __init__(self, modelo: str = "llama3.1", host: str = "http://localhost:11434"):
        self._modelo = modelo
        self._host = host
        self._usages: list = []

    @property
    def model_name(self) -> str:
        return self._modelo

    def usages(self) -> list:
        return self._usages

    def ask(self, system: str, user: str) -> str:
        import json
        import urllib.request

        payload = json.dumps(
            {
                "model": self._modelo,
                "system": system,
                "prompt": user,
                "stream": False,
            }
        ).encode()
        peticion = urllib.request.Request(
            f"{self._host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(peticion, timeout=300) as resp:
            datos = json.loads(resp.read())
        self._usages.append(
            {
                "prompt_tokens": datos.get("prompt_eval_count", 0),
                "completion_tokens": datos.get("eval_count", 0),
            }
        )
        return datos.get("response", "")


PROVEEDORES = {
    "gemini": (GeminiProvider, "gemini-2.5-flash"),
    "openai": (OpenAIProvider, "gpt-5.4-mini"),
    "claude": (ClaudeProvider, "claude-opus-4-8"),
    "ollama": (OllamaProvider, "llama3.1"),
}


def crear_provider(proveedor: str, modelo: str | None = None):
    if proveedor not in PROVEEDORES:
        raise ValueError(f"Proveedor desconocido: {proveedor}. Opciones: {sorted(PROVEEDORES)}")
    clase, default = PROVEEDORES[proveedor]
    return clase(modelo or default)
