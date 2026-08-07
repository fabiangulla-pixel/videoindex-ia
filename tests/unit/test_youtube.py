"""Descarga desde URL, con un yt-dlp falso: sin red y sin depender de que un
video siga existiendo mañana.

Lo que se prueba es la parte nuestra: qué opciones se le piden a yt-dlp, cómo
se normalizan sus metadatos y qué pasa cuando el archivo real no se llama
como yt-dlp había predicho (caso frecuente: pide m4a y el servidor da webm).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp

from videoindex.infrastructure.media import youtube


class FakeYDL:
    """Sustituto de yt_dlp.YoutubeDL: escribe un archivo y devuelve metadatos."""

    ultimas_opciones: dict = {}

    def __init__(self, opciones):
        self.opciones = opciones
        FakeYDL.ultimas_opciones = opciones

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    # Configurables por cada test
    info: dict = {}
    extension_real: str | None = None  # None = la que predice prepare_filename

    def extract_info(self, url, download=True):
        info = dict(self.info)
        info.setdefault("webpage_url", url)
        if download:
            destino = Path(self.prepare_filename(info))
            if self.extension_real:
                destino = destino.with_suffix(self.extension_real)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(b"audio-falso")
        return info

    def prepare_filename(self, info):
        datos = info["entries"][0] if info.get("entries") else info
        plantilla = self.opciones["outtmpl"]
        carpeta = Path(plantilla).parent
        return str(carpeta / f"{datos['title']} [{datos['id']}].m4a")


@pytest.fixture
def fake_ydl(monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    FakeYDL.info = {
        "id": "abc123",
        "title": "Mesa redonda sobre archivos",
        "uploader": "Anales UChile",
        "upload_date": "20260520",
        "duration": 3725,
    }
    FakeYDL.extension_real = None
    return FakeYDL


def test_es_url():
    assert youtube.es_url("https://www.youtube.com/watch?v=abc")
    assert youtube.es_url("  http://ejemplo.org/x  ")
    assert not youtube.es_url("C:/videos/clase.mp4")
    assert not youtube.es_url("")


def test_fecha_iso():
    assert youtube._fecha_iso("20260520") == "2026-05-20"
    assert youtube._fecha_iso(None) is None
    assert youtube._fecha_iso("2026") is None  # formato inesperado, no revienta
    assert youtube._fecha_iso("no-es-fecha") is None


def test_descarga_devuelve_metadatos_de_procedencia(fake_ydl, tmp_path):
    media = youtube.descargar_audio("https://youtu.be/abc123", tmp_path)

    assert media.ruta.exists()
    assert media.titulo == "Mesa redonda sobre archivos"
    assert media.canal == "Anales UChile"
    assert media.fecha_publicacion == "2026-05-20"
    assert media.duracion_s == 3725.0
    assert media.url == "https://youtu.be/abc123"


def test_pide_solo_audio_y_sin_playlist_ni_postproceso(fake_ydl, tmp_path):
    youtube.descargar_audio("https://youtu.be/abc123", tmp_path)
    opciones = FakeYDL.ultimas_opciones
    assert opciones["format"].startswith("bestaudio")
    assert opciones["noplaylist"] is True
    # Sin postprocesadores no hace falta ffmpeg instalado en la máquina.
    assert opciones["postprocessors"] == []


def test_encuentra_el_archivo_aunque_cambie_la_extension(fake_ydl, tmp_path):
    """yt-dlp predice el nombre antes de negociar el formato: si el servidor
    sirve webm en vez de m4a, hay que localizar lo que realmente se escribió."""
    FakeYDL.extension_real = ".webm"
    media = youtube.descargar_audio("https://youtu.be/abc123", tmp_path)
    assert media.ruta.exists()
    assert media.ruta.suffix == ".webm"


def test_url_de_playlist_toma_la_primera_entrada(fake_ydl, tmp_path):
    FakeYDL.info = {
        "entries": [
            {
                "id": "primera",
                "title": "Sesión 1",
                "uploader": "Canal",
                "upload_date": "20260101",
                "duration": 60,
            }
        ]
    }
    media = youtube.descargar_audio("https://youtube.com/playlist?list=X", tmp_path)
    assert media.titulo == "Sesión 1"


def test_si_no_queda_archivo_falla_claro(fake_ydl, tmp_path, monkeypatch):
    monkeypatch.setattr(FakeYDL, "extract_info", lambda self, url, download=True: dict(self.info))
    with pytest.raises(FileNotFoundError, match="no dejó archivo"):
        youtube.descargar_audio("https://youtu.be/abc123", tmp_path)


def test_el_progreso_se_reporta(fake_ydl, tmp_path):
    recibido: list[tuple[float, str]] = []
    youtube.descargar_audio(
        "https://youtu.be/abc123", tmp_path, lambda f, t: recibido.append((f, t))
    )
    # El hook lo llama yt-dlp de verdad; aquí se comprueba que la firma que
    # espera nuestro código es la que se pasa (sin hooks, no hay eventos).
    hook = FakeYDL.ultimas_opciones["progress_hooks"][0]
    hook({"status": "downloading", "total_bytes": 200, "downloaded_bytes": 50})
    hook({"status": "finished"})
    assert recibido[0][0] == 0.25
    assert recibido[-1][0] == 1.0
