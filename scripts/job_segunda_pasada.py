"""Segunda pasada de Whisper condicionada con las entidades ya descubiertas.

La primera pasada se hizo con un prompt genérico del tema. Ahora se sabe QUÉ
nombres propios aparecen de verdad — los leyó el OCR de los rótulos y los
créditos — así que se le pueden dar al modelo por adelantado.

No es fine-tuning: es condicionamiento en tiempo de inferencia. Whisper usa
`initial_prompt` como contexto previo, lo que sesga su decodificación hacia
esa grafía. Es la vía barata para el error que más cuesta corregir a mano en
un texto que va a publicarse: los nombres propios.

Reanudable igual que la primera pasada (JSONL con flush por segmento).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TRABAJO = Path(r"D:\Chile\workeo\transcripcion_work")
AUDIO = next(TRABAJO.glob("*.m4a"))
PARCIAL = TRABAJO / "segmentos_p2.jsonl"
SALIDA = TRABAJO / "segmentos_p2.json"

# Solo nombres con EVIDENCIA en el video (rótulos y créditos leídos por OCR)
# más las obras citadas en las tarjetas. No se añaden apellidos "probables":
# un nombre inventado en el prompt puede hacer que el modelo lo alucine.
PROMPT = (
    "Documental Estravagario sobre la literatura chilena en México. "
    "Intervienen Carla Ulloa, Soledad Bianchi, Myriam, Sandra Ivette González, "
    "Hernán Bravo, Rafael Vargas y Kemy. Narración de Valeria Figueroa; "
    "voces adicionales de José Luis Pérez Riaño. Se citan a Pablo Neruda, "
    "Gabriela Mistral, Roberto Bolaño y Alejandro Zambra, y las obras "
    "Confieso que he vivido, Canto General y Los detectives salvajes. "
    "Se mencionan la UNAM, la Fundación Pablo Neruda y Editorial Losada."
)


def log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def leer_parciales() -> list[dict]:
    if not PARCIAL.exists():
        return []
    datos = []
    for linea in PARCIAL.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            try:
                datos.append(json.loads(linea))
            except json.JSONDecodeError:
                log("aviso: última línea incompleta, se descarta")
    return datos


if __name__ == "__main__":
    from videoindex.infrastructure.transcription.faster_whisper_provider import (
        FasterWhisperProvider,
    )

    hechos = leer_parciales()
    desde = max((s["end"] for s in hechos), default=0.0)
    if hechos:
        log(f"Reanudando desde {desde / 60:.1f} min ({len(hechos)} segmentos)")
    log(f"Prompt de {len(PROMPT.split())} palabras con las entidades del video")

    proveedor = FasterWhisperProvider(
        modelo="large-v3-turbo",
        idioma="es",
        compute_type="int8",
        beam_size=5,
        initial_prompt=PROMPT,
        condition_on_previous_text=True,
    )
    inicio = time.time()
    ultimo = [desde / 3223.4]
    archivo = PARCIAL.open("a", encoding="utf-8")

    def guardar(seg) -> None:
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

    def progreso(f: float) -> None:
        if f - ultimo[0] >= 0.05:
            ultimo[0] = f
            t = time.time() - inicio
            avance = max(f - desde / 3223.4, 0.01)
            log(f"pasada 2: {f * 100:.0f}%  (faltan ~{(t / avance - t) / 60:.0f} min)")

    try:
        proveedor.transcribir(str(AUDIO), "estravagario-p2", progreso, desde, guardar)
    finally:
        archivo.close()

    datos = leer_parciales()
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Pasada 2 lista: {len(datos)} segmentos en {(time.time() - inicio) / 60:.1f} min")
