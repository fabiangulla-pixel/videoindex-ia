"""Smoke offscreen de los diálogos nuevos: URL, Transcripción y Configuración.

Invoca los widgets DIRECTAMENTE (nada de clics por coordenadas ni capturas de
pantalla): se construyen, se les mete estado y se leen sus propiedades. Sale
solo con código 0/1.

Uso:  .venv\\Scripts\\python.exe scripts\\smoke_dialogos.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # sin ventana real
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")
# BD desechable: el smoke no puede tocar la biblioteca real del usuario.
_TEMP = Path(tempfile.mkdtemp(prefix="videoindex_smoke_"))
os.environ["VIDEOINDEX_DATA"] = str(_TEMP)

from PySide6.QtWidgets import QApplication  # noqa: E402

from videoindex.config import paths  # noqa: E402
from videoindex.domain.models import Video  # noqa: E402
from videoindex.infrastructure.db.connection import conectar  # noqa: E402
from videoindex.infrastructure.db.repositories import SegmentRepo, VideoRepo  # noqa: E402
from videoindex.presentation.settings_dialog import ApiSettingsDialog  # noqa: E402
from videoindex.presentation.transcript_dialog import TranscriptDialog  # noqa: E402
from videoindex.presentation.url_dialog import UrlDialog  # noqa: E402

fallos: list[str] = []


def comprobar(condicion: bool, descripcion: str) -> None:
    print(f"  {'[OK]  ' if condicion else '[FALLO]'} {descripcion}", flush=True)
    if not condicion:
        fallos.append(descripcion)


def sembrar_video() -> tuple[str, str]:
    from videoindex.domain.models import TranscriptSegment

    paths.ensure_dirs()
    con = conectar(paths.DB_PATH)
    try:
        video = Video(
            video_id=str(uuid4()),
            title="Entrevista de prueba",
            path=str(_TEMP / "audio.m4a"),
            checksum=uuid4().hex,
            duration_seconds=120.0,
            source_url="https://www.youtube.com/watch?v=demo",
            source_channel="Canal de prueba",
            source_published_at="2026-05-20",
        )
        VideoRepo(con).guardar(video)
        SegmentRepo(con).guardar_lote(
            [
                TranscriptSegment(
                    str(uuid4()), video.video_id, 0.0, 5.0, "P", "P", 0.9, "SPEAKER_00"
                ),
                TranscriptSegment(
                    str(uuid4()), video.video_id, 5.0, 9.0, "R", "R", 0.9, "SPEAKER_01"
                ),
                TranscriptSegment(
                    str(uuid4()), video.video_id, 9.0, 12.0, "R2", "R2", 0.9, "SPEAKER_01"
                ),
            ]
        )
    finally:
        con.close()
    return video.video_id, video.title


app = QApplication(sys.argv)

print("UrlDialog:", flush=True)
url = UrlDialog()
comprobar(
    not url._botones.button(url._botones.StandardButton.Ok).isEnabled(),
    "sin URLs no deja descargar",
)
url._urls.setPlainText(
    "https://www.youtube.com/watch?v=uno\nesto no es una url\nhttps://youtu.be/dos\nhttps://youtu.be/dos"
)
comprobar(
    url.urls() == ["https://www.youtube.com/watch?v=uno", "https://youtu.be/dos"],
    "filtra basura y duplicados",
)
comprobar(
    url._botones.button(url._botones.StandardButton.Ok).isEnabled(),
    "con URLs válidas habilita el botón",
)

print("TranscriptDialog:", flush=True)
video_id, titulo = sembrar_video()
transcripcion = TranscriptDialog(video_id, titulo)
comprobar(
    transcripcion._tabla.rowCount() == 2,
    f"agrupa 3 segmentos en 2 intervenciones (vio {transcripcion._tabla.rowCount()})",
)
comprobar(
    set(transcripcion._campos) == {"SPEAKER_00", "SPEAKER_01"},
    "ofrece un campo por hablante detectado",
)
transcripcion._campos["SPEAKER_00"].setText("Entrevistadora")
transcripcion._renombrar("SPEAKER_00")
comprobar(
    transcripcion._tabla.item(0, 1).text() == "Entrevistadora", "renombrar se refleja en la tabla"
)

saltos: list[float] = []
transcripcion.saltar_a.connect(saltos.append)
transcripcion._saltar(transcripcion._tabla.item(1, 2))
comprobar(saltos == [5.0], f"doble clic emite el segundo exacto (vio {saltos})")

print("ApiSettingsDialog:", flush=True)
config = ApiSettingsDialog()
comprobar(config._modelo_whisper.count() >= 6, "lista los modelos de Whisper")
config._diarizacion.setChecked(True)
config._n_hablantes.setValue(0)
comprobar(config._umbral.isEnabled(), "en automático el umbral se puede tocar")
config._n_hablantes.setValue(2)
comprobar(not config._umbral.isEnabled(), "con nº fijo de hablantes el umbral se bloquea")
config._diarizacion.setChecked(False)
comprobar(not config._n_hablantes.isEnabled(), "sin diarización se bloquean sus ajustes")

print(
    f"\n{'SMOKE DIALOGOS OK' if not fallos else 'SMOKE DIALOGOS FALLO: ' + '; '.join(fallos)}",
    flush=True,
)
os._exit(0 if not fallos else 1)
