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


def test_guardar_transcripcion_no_pisa_las_preferencias_de_ia(tmp_path, monkeypatch):
    """Las dos pestañas de Configuración escriben el MISMO archivo: guardar una
    no puede borrar la otra (por eso se mezcla en vez de reemplazar)."""
    monkeypatch.setenv("VIDEOINDEX_DATA", str(tmp_path))
    import importlib

    from videoindex.config import paths

    importlib.reload(paths)

    settings.guardar_preferencias_rag("claude", "claude-sonnet-5")
    settings.guardar_preferencias_transcripcion("large-v3-turbo", "es", True, 2, 0.55)

    # Reinicio simulado: valores por defecto en memoria y recarga desde disco.
    settings.SETTINGS.rag.proveedor = "gemini"
    settings.SETTINGS.transcription.modelo = "small"
    settings.SETTINGS.diarization.n_hablantes = 0
    settings.cargar_preferencias_rag()
    settings.cargar_preferencias_transcripcion()

    assert settings.SETTINGS.rag.proveedor == "claude"  # sobrevivió
    assert settings.SETTINGS.transcription.modelo == "large-v3-turbo"
    assert settings.SETTINGS.diarization.activa is True
    assert settings.SETTINGS.diarization.n_hablantes == 2
    assert settings.SETTINGS.diarization.umbral_distancia == 0.55

    importlib.reload(paths)


def test_factor_de_tiempo_depende_del_modelo_y_de_la_diarizacion():
    assert settings.factor_tiempo("small", False) == 0.5
    assert settings.factor_tiempo("large-v3", False) > settings.factor_tiempo("small", False)
    # Diarizar añade un sobrecosto, nunca resta.
    assert settings.factor_tiempo("small", True) > settings.factor_tiempo("small", False)
    # Un modelo desconocido no revienta el ETA: cae al factor por defecto.
    assert settings.factor_tiempo("modelo-inventado", False) > 0
