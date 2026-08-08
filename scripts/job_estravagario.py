"""Job de transcripción profesional del documental "Estravagario".

Corre fuera de la biblioteca de la app (no toca data/videoindex.db).

**Reanudable por diseño.** La transcripción se escribe segmento a segmento en
un JSONL con flush inmediato: si la máquina se suspende, se cierra la tapa o
se corta la sesión, al relanzar continúa desde el último segmento guardado en
vez de volver a pagar los minutos de CPU. Se aprendió por las malas: una
primera versión que solo guardaba al final perdió 65 min de cómputo al 84 %.

Etapas y checkpoints:
  1. transcribir -> segmentos.jsonl  (incremental, reanudable)
                    segmentos.json   (consolidado al terminar)
  2. diarizar    -> turnos.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TRABAJO = Path(r"D:\Chile\workeo\transcripcion_work")
AUDIO = next(TRABAJO.glob("*.m4a"))
PARCIAL = TRABAJO / "segmentos.jsonl"
SEGMENTOS = TRABAJO / "segmentos.json"
TURNOS = TRABAJO / "turnos.json"

# Contexto para Whisper: mejora nombres propios y terminología del dominio,
# que es justo lo que más caro sale corregir a mano después.
CONTEXTO = (
    "Documental sobre la literatura chilena en México y el exilio: "
    "Pablo Neruda, Estravagario, Gabriela Mistral, poesía, Universidad "
    "Nacional Autónoma de México, Santiago, Ciudad de México."
)


def log(mensaje: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {mensaje}", flush=True)


def _leer_parciales() -> list[dict]:
    """Lo ya transcrito. Una línea corrupta (el proceso murió a media
    escritura) se descarta en vez de invalidar todo el archivo."""
    if not PARCIAL.exists():
        return []
    datos = []
    for linea in PARCIAL.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            datos.append(json.loads(linea))
        except json.JSONDecodeError:
            log("aviso: última línea del checkpoint incompleta, se descarta")
    return datos


def transcribir() -> list[dict]:
    if SEGMENTOS.exists():
        log("segmentos.json ya existe, se reutiliza")
        return json.loads(SEGMENTOS.read_text(encoding="utf-8"))

    from videoindex.infrastructure.transcription.faster_whisper_provider import (
        FasterWhisperProvider,
    )

    hechos = _leer_parciales()
    desde = max((s["end"] for s in hechos), default=0.0)
    if hechos:
        log(
            f"Reanudando: {len(hechos)} segmentos ya guardados, se sigue desde {desde / 60:.1f} min"
        )

    proveedor = FasterWhisperProvider(
        modelo="large-v3-turbo",
        idioma="es",
        compute_type="int8",
        beam_size=5,
        initial_prompt=CONTEXTO,
        condition_on_previous_text=True,
    )
    inicio = time.time()
    ultimo = [0.0]
    archivo = PARCIAL.open("a", encoding="utf-8")

    def guardar(seg) -> None:
        """Escribe y hace flush en cada segmento: el coste es despreciable
        frente a lo que cuesta volver a transcribir."""
        archivo.write(
            json.dumps(
                {
                    "segment_id": seg.segment_id,
                    "start": seg.start_time,
                    "end": seg.end_time,
                    "texto": seg.clean_text,
                    "raw": seg.raw_text,
                    "confianza": seg.confidence,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        archivo.flush()

    def progreso(fraccion: float) -> None:
        if fraccion - ultimo[0] >= 0.02:
            ultimo[0] = fraccion
            transcurrido = time.time() - inicio
            avance = max(fraccion - desde / 3223.4, 0.01)
            log(
                f"transcribiendo {fraccion * 100:.0f}%  (faltan ~{(transcurrido / avance - transcurrido) / 60:.0f} min)"
            )

    try:
        proveedor.transcribir(str(AUDIO), "estravagario", progreso, desde, guardar)
    finally:
        archivo.close()

    datos = _leer_parciales()
    log(f"Transcripción lista: {len(datos)} segmentos en {(time.time() - inicio) / 60:.1f} min")
    SEGMENTOS.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def diarizar(segmentos: list[dict]) -> list[dict]:
    if TURNOS.exists():
        log("turnos.json ya existe, se reutiliza")
        return json.loads(TURNOS.read_text(encoding="utf-8"))

    from videoindex.infrastructure.diarization.ecapa_provider import EcapaDiarizationProvider

    log("Diarizando (ECAPA, automático: no sabemos cuántas voces hay)…")
    inicio = time.time()
    regiones = [(s["start"], s["end"]) for s in segmentos]
    ultimo = [0.0]

    def progreso(f: float) -> None:
        if f - ultimo[0] >= 0.1:
            ultimo[0] = f
            log(f"voces {f * 100:.0f}%")

    turnos = EcapaDiarizationProvider(n_hablantes=0).diarizar(str(AUDIO), regiones, progreso)
    voces = sorted({t.speaker for t in turnos})
    log(
        f"Diarización lista: {len(turnos)} turnos, {len(voces)} voces "
        f"en {(time.time() - inicio) / 60:.1f} min"
    )

    datos = [{"start": t.start_time, "end": t.end_time, "speaker": t.speaker} for t in turnos]
    TURNOS.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


if __name__ == "__main__":
    log(f"Audio: {AUDIO.name}")
    diarizar(transcribir())
    log("JOB TERMINADO")
