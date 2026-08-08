"""Descarga de audio desde una URL (YouTube y los ~1800 sitios de yt-dlp).

Decisiones:
- Solo AUDIO (`bestaudio`, preferentemente m4a). Es lo único que el pipeline
  necesita — transcribir, diarizar, indexar — y baja en un tramo de lo que
  tarda el video completo. Un m4a no requiere postproceso, así que NO hace
  falta ffmpeg instalado: PyAV y faster-whisper lo decodifican directo.
- `noplaylist`: una URL con `list=` baja solo ese video, no el curso entero.
  Para varios, se pasan varias URLs (la GUI acepta una por línea).
- Los metadatos (título real, canal, fecha) se guardan con el video: son la
  ficha de procedencia que hay que citar si la transcripción se publica.

Sobre permisos: descargar material ajeno requiere autorización del titular
(los términos de YouTube no la conceden por defecto). Esta herramienta no la
verifica; asume que quien la usa ya la tiene.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_URL = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class MediaDescargado:
    ruta: Path
    titulo: str
    url: str
    canal: str | None = None
    fecha_publicacion: str | None = None  # ISO YYYY-MM-DD
    duracion_s: float | None = None


def es_url(texto: str) -> bool:
    return bool(_URL.match(texto.strip()))


def _fecha_iso(upload_date: str | None) -> str | None:
    """yt-dlp entrega 'YYYYMMDD'; se guarda como 'YYYY-MM-DD'."""
    if not upload_date or len(upload_date) != 8 or not upload_date.isdigit():
        return None
    return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"


def descargar_audio(
    url: str,
    carpeta_destino: str | Path,
    progreso: Callable[[float, str], None] | None = None,
    con_imagen: bool = False,
) -> MediaDescargado:
    """Baja `url` a `carpeta_destino`: solo el audio, o audio + imagen.

    `con_imagen=True` hace falta para poder leer después los rótulos
    sobreimpresos e identificar a los hablantes por su nombre — sin imagen no
    hay nada que leer. Pesa bastante más y tarda más en bajar.

    En ese modo se pide un stream **progresivo** (audio y video ya juntos en
    un archivo) en vez del mejor de cada tipo por separado: unir dos pistas
    exige ffmpeg instalado, y aquí no se da por supuesto. El precio es una
    resolución algo menor, suficiente para un rótulo.

    progreso(fraccion 0..1, texto): yt-dlp no siempre conoce el tamaño total
    (streams sin Content-Length), así que la fracción puede quedarse en 0
    mientras el texto sí informa; quien la consume debe tolerarlo.
    """
    import yt_dlp

    carpeta = Path(carpeta_destino)
    carpeta.mkdir(parents=True, exist_ok=True)

    def _hook(d: dict) -> None:
        if progreso is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            bajado = d.get("downloaded_bytes") or 0
            fraccion = bajado / total if total else 0.0
            progreso(min(1.0, fraccion), f"Descargando… {d.get('_percent_str', '').strip()}")
        elif d.get("status") == "finished":
            progreso(1.0, "Descarga terminada, verificando…")

    # Con imagen: se exige un stream que ya traiga las dos pistas juntas
    # (acodec y vcodec presentes), para no depender de ffmpeg al unirlas.
    formato = (
        "best[ext=mp4][acodec!=none][vcodec!=none]/best[acodec!=none][vcodec!=none]/best"
        if con_imagen
        else "bestaudio[ext=m4a]/bestaudio/best"
    )
    opciones = {
        "format": formato,
        "outtmpl": str(carpeta / "%(title).120B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [_hook],
        # Sin postproceso: no se recodifica ni se extrae con ffmpeg, que no
        # tiene por qué estar instalado en la máquina del usuario.
        "postprocessors": [],
    }

    with yt_dlp.YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(url, download=True)
        # Una URL de playlist con noplaylist puede aun así devolver entradas.
        if info.get("entries"):
            info = info["entries"][0]
        ruta = Path(ydl.prepare_filename(info))

    if not ruta.exists():
        # prepare_filename predice la extensión antes de negociar el formato;
        # si el servidor sirvió otra (webm en vez de m4a), se busca el archivo
        # realmente escrito por id, que sí es estable.
        candidatos = sorted(carpeta.glob(f"*[[]{info.get('id', '')}[]]*"))
        if not candidatos:
            raise FileNotFoundError(f"La descarga no dejó archivo en {carpeta} para {url}")
        ruta = candidatos[0]

    duracion = info.get("duration")
    return MediaDescargado(
        ruta=ruta,
        titulo=info.get("title") or ruta.stem,
        url=info.get("webpage_url") or url,
        canal=info.get("uploader") or info.get("channel"),
        fecha_publicacion=_fecha_iso(info.get("upload_date")),
        duracion_s=float(duracion) if duracion else None,
    )
