"""Guardado seguro de API keys — Windows Credential Manager vía keyring.

Adaptado de ReactivosFlow (infra/security/secrets.py). Nunca texto plano:
las claves no viven en archivos ni en el repo, solo en el almacén de
credenciales del sistema operativo, por proveedor.
"""

from __future__ import annotations

import contextlib

KEYRING_SERVICE = "VideoIndexIA"


def save_api_key(provider: str, api_key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, provider, api_key)


def load_api_key(provider: str) -> str | None:
    import keyring

    try:
        return keyring.get_password(KEYRING_SERVICE, provider)
    except Exception:
        return None


def delete_api_key(provider: str) -> None:
    import keyring

    with contextlib.suppress(Exception):
        keyring.delete_password(KEYRING_SERVICE, provider)
