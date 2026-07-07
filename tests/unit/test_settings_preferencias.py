"""Persistencia de proveedor/modelo elegidos en Configuración (no es secreto)."""

from videoindex.config import settings


def test_modelo_recomendado_es_el_primero_del_catalogo():
    assert settings.modelo_recomendado("gemini") == "gemini-2.5-flash"
    assert settings.modelo_recomendado("proveedor-inexistente") == ""


def test_guardar_y_cargar_preferencias(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOINDEX_DATA", str(tmp_path))
    # paths.DATA_DIR se calcula al importar el módulo; forzamos recarga.
    import importlib

    from videoindex.config import paths

    importlib.reload(paths)

    settings.guardar_preferencias_rag("claude", "claude-sonnet-5")
    assert settings.SETTINGS.rag.proveedor == "claude"
    assert settings.SETTINGS.rag.modelo == "claude-sonnet-5"

    # Simula un reinicio de la app: resetear en memoria y recargar de disco.
    settings.SETTINGS.rag.proveedor = "gemini"
    settings.SETTINGS.rag.modelo = "gemini-2.5-flash"
    settings.cargar_preferencias_rag()
    assert settings.SETTINGS.rag.proveedor == "claude"
    assert settings.SETTINGS.rag.modelo == "claude-sonnet-5"

    importlib.reload(paths)  # no dejar el módulo con la ruta de prueba


def test_cargar_preferencias_sin_archivo_no_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOINDEX_DATA", str(tmp_path / "no_existe"))
    import importlib

    from videoindex.config import paths

    importlib.reload(paths)
    settings.cargar_preferencias_rag()  # no debe lanzar
    importlib.reload(paths)
