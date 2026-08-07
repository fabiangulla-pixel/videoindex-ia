"""Job de transcripción profesional del documental "Estravagario".

Corre fuera de la biblioteca de la app (no toca data/videoindex.db): deja
resultados intermedios en JSON para poder retomar sin re-pagar el tiempo de
CPU, que es la parte cara.

Etapas, cada una con su JSON de checkpoint:
  1. transcribir  -> segmentos.json
  2. diarizar     -> turnos.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TRABAJO = Path(r"D:\Chile\workeo\transcripcion_work")
AUDIO = next(TRABAJO.glob("*.m4a"))
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


def transcribir() -> list[dict]:
    if SEGMENTOS.exists():
        log(f"segmentos.json ya existe, se reutiliza ({SEGMENTOS})")
        return json.loads(SEGMENTOS.read_text(encoding="utf-8"))

    from videoindex.infrastructure.transcription.faster_whisper_provider import (
        FasterWhisperProvider,
    )

    log("Cargando large-v3-turbo (descarga la primera vez)…")
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

    def progreso(fraccion: float) -> None:
        if fraccion - ultimo[0] >= 0.02:  # avisar cada 2 %
            ultimo[0] = fraccion
            transcurrido = time.time() - inicio
            resta = transcurrido / max(fraccion, 0.01) - transcurrido
            log(f"transcribiendo {fraccion * 100:.0f}%  (faltan ~{resta / 60:.0f} min)")

    segmentos = proveedor.transcribir(str(AUDIO), "estravagario", progreso)
    log(f"Transcripción lista: {len(segmentos)} segmentos en {(time.time() - inicio) / 60:.1f} min")

    datos = [
        {
            "segment_id": s.segment_id,
            "start": s.start_time,
            "end": s.end_time,
            "texto": s.clean_text,
            "raw": s.raw_text,
            "confianza": s.confidence,
        }
        for s in segmentos
    ]
    SEGMENTOS.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def diarizar(segmentos: list[dict]) -> list[dict]:
    if TURNOS.exists():
        log(f"turnos.json ya existe, se reutiliza ({TURNOS})")
        return json.loads(TURNOS.read_text(encoding="utf-8"))

    from videoindex.infrastructure.diarization.ecapa_provider import EcapaDiarizationProvider

    log("Diarizando (ECAPA, automático: no sabemos cuántas voces hay)…")
    inicio = time.time()
    regiones = [(s["start"], s["end"]) for s in segmentos]
    proveedor = EcapaDiarizationProvider(n_hablantes=0)
    turnos = proveedor.diarizar(
        str(AUDIO),
        regiones,
        lambda f: log(f"voces {f * 100:.0f}%") if int(f * 100) % 20 == 0 else None,
    )
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
    segs = transcribir()
    diarizar(segs)
    log("JOB TERMINADO")
