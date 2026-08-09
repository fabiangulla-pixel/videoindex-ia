"""El modelo de OCR en español debe bajarse solo la primera vez.

Regresión de un fallo SILENCIOSO: el modelo estaba instalado a mano en el
equipo de desarrollo, la carpeta portable no lo llevaba, y en otro PC el OCR
caía a inglés — leyendo los rótulos sin tildes ni eñes — con un aviso que
solo aparecía en el log. Los nombres habrían salido mal en el documento
entregado sin que nadie se enterase.
"""

from __future__ import annotations

from videoindex.infrastructure.ocr import tesseract_ocr


def test_descarga_el_modelo_si_falta(tmp_path, monkeypatch):
    llamadas = []

    def falso_urlretrieve(url, destino):
        llamadas.append(url)
        destino.write_bytes(b"modelo-falso")

    monkeypatch.setattr("urllib.request.urlretrieve", falso_urlretrieve)
    tesseract_ocr._descargar_modelo_espanol(tmp_path / "tessdata")

    assert llamadas and llamadas[0].endswith("spa.traineddata")
    assert (tmp_path / "tessdata" / "spa.traineddata").exists()
    # El archivo temporal no debe quedarse por ahí.
    assert not (tmp_path / "tessdata" / "spa.traineddata.parcial").exists()


def test_una_descarga_cortada_no_deja_un_modelo_truncado(tmp_path, monkeypatch):
    """Si se corta a medias, Tesseract no debe encontrar un archivo a medio
    escribir y darlo por bueno en el siguiente arranque."""

    def falla(url, destino):
        destino.write_bytes(b"mitad")
        raise OSError("conexión interrumpida")

    monkeypatch.setattr("urllib.request.urlretrieve", falla)
    tesseract_ocr._descargar_modelo_espanol(tmp_path / "tessdata")

    assert not (tmp_path / "tessdata" / "spa.traineddata").exists()
    assert not (tmp_path / "tessdata" / "spa.traineddata.parcial").exists()


def test_un_fallo_de_red_no_revienta_la_app(tmp_path, monkeypatch):
    """Sin internet la app debe seguir arrancando; el OCR cae a inglés."""

    def sin_red(url, destino):
        raise OSError("sin conexión")

    monkeypatch.setattr("urllib.request.urlretrieve", sin_red)
    tesseract_ocr._descargar_modelo_espanol(tmp_path / "tessdata")  # no lanza
