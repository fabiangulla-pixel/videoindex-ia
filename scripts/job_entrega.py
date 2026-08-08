"""Ensambla el paquete editorial a partir de los tres checkpoints del trabajo.

  segmentos.json  (audio -> texto)
  turnos.json     (audio -> quién habla)
  rotulos.json    (imagen -> cómo se llama)
        |
        v
  resultado_transcripcion/  (los ocho documentos)

Se puede volver a lanzar tantas veces como haga falta: no re-procesa nada,
solo vuelve a escribir los documentos con lo ya calculado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TRABAJO = Path(r"D:\Chile\workeo\transcripcion_work")
RESULTADO = Path(r"D:\Chile\workeo\resultado_transcripcion")
VIDEO = Path(r"D:\Chile\workeo\video\videoplayback.mp4")
URL = "https://www.youtube.com/watch?v=1tq_BbCzp80"
TITULO = "Estravagario: la literatura chilena en México"
CANAL = "YouTube"


def cargar():
    from videoindex.application.rotulos_service import Rotulo
    from videoindex.domain.models import SpeakerTurn, TranscriptSegment

    # El consolidado si ya existe; si no, el checkpoint incremental. Así el
    # paquete se puede armar aunque la transcripción siga en marcha (útil
    # para revisar el formato sin esperar a que termine).
    ruta_consolidado = TRABAJO / "segmentos.json"
    if ruta_consolidado.exists():
        datos_seg = json.loads(ruta_consolidado.read_text(encoding="utf-8"))
    else:
        datos_seg = [
            json.loads(linea)
            for linea in (TRABAJO / "segmentos.jsonl").read_text(encoding="utf-8").splitlines()
            if linea.strip()
        ]
    segmentos = [
        TranscriptSegment(
            segment_id=s["segment_id"],
            video_id="estravagario",
            start_time=s["start"],
            end_time=s["end"],
            raw_text=s["raw"],
            clean_text=s["texto"],
            confidence=s["confianza"],
        )
        for s in datos_seg
    ]
    ruta_turnos = TRABAJO / "turnos.json"
    turnos = (
        [
            SpeakerTurn(t["start"], t["end"], t["speaker"])
            for t in json.loads(ruta_turnos.read_text(encoding="utf-8"))
        ]
        if ruta_turnos.exists()
        else []
    )
    ruta_rotulos = TRABAJO / "rotulos.json"
    rotulos = (
        [Rotulo(**r) for r in json.loads(ruta_rotulos.read_text(encoding="utf-8"))]
        if ruta_rotulos.exists()
        else []
    )
    return segmentos, turnos, rotulos, datos_seg


def main() -> int:
    from videoindex.application.entrega_editorial import Contexto, generar_paquete
    from videoindex.application.identificacion_service import (
        detectar_inicio_creditos,
        identificar,
        interpretar_cita,
    )
    from videoindex.domain.diarization import asignar_hablantes
    from videoindex.infrastructure.media.probe import duracion_segundos

    segmentos, turnos, rotulos, crudos = cargar()
    asignar_hablantes(segmentos, turnos)

    identidades = identificar(turnos, rotulos, crudos)
    citas = [c for r in rotulos if (c := interpretar_cita(r)) is not None]
    duracion = duracion_segundos(VIDEO) or 0.0
    fin_contenido = detectar_inicio_creditos(rotulos, duracion)

    audio = next(TRABAJO.glob("*.m4a"))
    contexto = Contexto(
        titulo=TITULO,
        archivo=audio.name,
        duracion_s=duracion,
        url=URL,
        canal=CANAL,
        modelo_transcripcion="faster-whisper large-v3-turbo (CPU, int8)",
        modelo_diarizacion="speechbrain ECAPA-TDNN + agrupamiento aglomerativo",
        modelo_ocr="Tesseract 5.4 (spa) sobre fotogramas cada 2 s",
        notas=[
            "El mp4 descargado por el usuario no tenía pista de audio "
            "(solo video): el audio se bajó aparte desde la URL original.",
            f"{len(rotulos)} rótulos leídos en pantalla por consenso temporal.",
        ],
    )

    salidas = generar_paquete(
        RESULTADO, contexto, segmentos, identidades, citas, len(rotulos), fin_contenido
    )

    print(f"\nDuración procesada: {contexto.duracion_s / 60:.1f} min")
    print(f"Voces distinguidas: {len(identidades)}")
    print(f"Con nombre propio : {sum(1 for i in identidades if i.nombre)}")
    print(f"Sin identificar   : {sum(1 for i in identidades if not i.nombre)}")
    print(f"Textos literarios : {len(citas)}")
    print("\nParticipantes:")
    for ident in identidades:
        print(
            f"  {ident.descriptor:52} {ident.confianza:6} {ident.segundos_hablados / 60:5.1f} min"
        )
    print(f"\nArchivos en {RESULTADO}:")
    for ruta in salidas.values():
        print(f"  - {ruta.name}  ({ruta.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
