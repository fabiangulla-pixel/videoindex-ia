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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from videoindex.config import paths  # noqa: E402
from videoindex.domain.models import Video  # noqa: E402
from videoindex.infrastructure.db.connection import conectar  # noqa: E402
from videoindex.infrastructure.db.repositories import SegmentRepo, VideoRepo  # noqa: E402
from videoindex.presentation.settings_dialog import ApiSettingsDialog  # noqa: E402
from videoindex.presentation.transcript_dialog import TranscriptDialog  # noqa: E402
from videoindex.presentation.url_dialog import UrlDialog  # noqa: E402

# La consola de Windows es cp1252 y los rotulos de la app llevan emojis:
# sin esto, imprimir un resultado revienta el smoke con UnicodeEncodeError.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

print("LibraryView (botones visibles):", flush=True)
from videoindex.presentation.library_view import LibraryView  # noqa: E402

biblioteca = LibraryView()
etiquetas = [
    biblioteca.boton_agregar.text(),
    biblioteca.boton_url.text(),
    biblioteca.boton_transcripcion.text(),
    biblioteca.boton_identificar.text(),
    biblioteca.boton_paquete.text(),
]
comprobar("URL" in etiquetas[1], "el boton de descargar por URL esta a la vista")
comprobar(
    any("Transcripción" in e for e in etiquetas)
    and any("Identificar" in e for e in etiquetas)
    and any("Paquete" in e for e in etiquetas),
    f"las tres acciones principales tienen boton propio (vio {etiquetas[2:]})",
)
comprobar(
    not biblioteca.boton_identificar.isEnabled(),
    "sin video seleccionado, las acciones sobre un video estan deshabilitadas",
)
comprobar(
    "Selecciona un video" in biblioteca.etiqueta_seleccion.text(),
    "y el rotulo explica por que",
)

print("IdentidadesDialog:", flush=True)
from videoindex.application.identificacion_service import ALTO, BAJO, Identidad  # noqa: E402
from videoindex.presentation.identidades_dialog import IdentidadesDialog  # noqa: E402

propuestas = [
    Identidad(
        speaker_label="SPEAKER_00",
        nombre="CARLA ULLOA",
        funcion="HISTORIADORA",
        confianza=ALTO,
        primera_aparicion=205.0,
        evidencias=["Rótulo en pantalla [00:03:25]"],
    ),
    Identidad(
        speaker_label="SPEAKER_01",
        nombre="Gabriela Mistral",
        confianza="MEDIO",
        primera_aparicion=1301.0,
        evidencias=["Rótulo sin cargo: puede ser un pie de foto"],
    ),
    Identidad(
        speaker_label="SPEAKER_02",
        confianza=BAJO,
        es_voz_en_off=True,
        primera_aparicion=0.0,
        segundos_hablados=900.0,
    ),
]
ident = IdentidadesDialog(propuestas, n_rotulos=33)
comprobar(ident._tabla.rowCount() == 3, "una fila por voz")
marcadas = ident.nombres_confirmados()
comprobar(
    marcadas == {"SPEAKER_00": "CARLA ULLOA"},
    f"solo la de confianza ALTA viene marcada (vio {marcadas})",
)
ident._tabla.item(1, 0).setCheckState(Qt.CheckState.Checked)
ident._tabla.item(1, 2).setText("Gabriela Mistral")
comprobar(
    "SPEAKER_01" in ident.nombres_confirmados(), "marcar a mano incorpora la propuesta dudosa"
)
ident._tabla.item(0, 2).setText("   ")
comprobar(
    "SPEAKER_00" not in ident.nombres_confirmados(),
    "un nombre vacio no se guarda aunque este marcado",
)

print(
    f"\n{'SMOKE DIALOGOS OK' if not fallos else 'SMOKE DIALOGOS FALLO: ' + '; '.join(fallos)}",
    flush=True,
)
os._exit(0 if not fallos else 1)
