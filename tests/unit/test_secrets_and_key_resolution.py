"""Resolución de API keys: keyring primero, variable de entorno como fallback.

No se ejercita el keyring real de Windows en tests (no hay Credential Manager
en CI ni motivo para tocarlo); se monkeypatchea load_api_key para simular
ambos caminos.
"""

import pytest

from videoindex.infrastructure.llm import providers


def test_key_usa_keyring_si_esta_disponible(monkeypatch):
    monkeypatch.setattr(providers, "load_api_key", lambda proveedor: "clave-del-keyring")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert providers._key("GEMINI_API_KEY", "gemini", "Gemini") == "clave-del-keyring"


def test_key_cae_a_env_var_si_keyring_vacio(monkeypatch):
    monkeypatch.setattr(providers, "load_api_key", lambda proveedor: None)
    monkeypatch.setenv("GEMINI_API_KEY", "clave-del-env")
    assert providers._key("GEMINI_API_KEY", "gemini", "Gemini") == "clave-del-env"


def test_key_prefiere_keyring_sobre_env_var(monkeypatch):
    monkeypatch.setattr(providers, "load_api_key", lambda proveedor: "clave-del-keyring")
    monkeypatch.setenv("GEMINI_API_KEY", "clave-del-env")
    assert providers._key("GEMINI_API_KEY", "gemini", "Gemini") == "clave-del-keyring"


def test_key_sin_ninguna_fuente_lanza_error_util(monkeypatch):
    monkeypatch.setattr(providers, "load_api_key", lambda proveedor: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(providers.ProveedorNoConfigurado, match="Gemini"):
        providers._key("GEMINI_API_KEY", "gemini", "Gemini")


def test_crear_provider_proveedor_desconocido():
    with pytest.raises(ValueError, match="Proveedor desconocido"):
        providers.crear_provider("no-existe")


def test_crear_provider_usa_default_si_modelo_vacio():
    p = providers.crear_provider("gemini", None)
    assert p.model_name == "gemini-2.5-flash"
