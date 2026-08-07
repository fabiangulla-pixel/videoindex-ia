"""Pasada de OCR sobre el video completo -> rotulos.json (checkpoint).

Va aparte del job de audio a propósito: son dos recursos distintos (imagen
vs. sonido) y así pueden correr en paralelo y reanudarse por separado.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

VIDEO = Path(r"D:\Chile\workeo\video\videoplayback.mp4")
DESTINO = Path(r"D:\Chile\workeo\transcripcion_work\rotulos.json")
CADA_S = 2.0  # un rótulo dura 6-8 s: con 2 s se lee 3-4 veces, basta para el consenso


def log(mensaje: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {mensaje}", flush=True)


if __name__ == "__main__":
    from videoindex.application.rotulos_service import detectar_rotulos
    from videoindex.infrastructure.media.probe import duracion_segundos

    duracion = duracion_segundos(VIDEO) or 0.0
    log(f"OCR de {VIDEO.name} ({duracion / 60:.1f} min) cada {CADA_S} s")
    inicio = time.time()
    ultimo = [0.0]

    def progreso(f: float) -> None:
        if f - ultimo[0] >= 0.05:
            ultimo[0] = f
            transcurrido = time.time() - inicio
            log(
                f"OCR {f * 100:.0f}%  (faltan ~{(transcurrido / max(f, 0.01) - transcurrido) / 60:.0f} min)"
            )

    rotulos = detectar_rotulos(VIDEO, cada_s=CADA_S, hasta_s=duracion, progreso=progreso)
    log(f"{len(rotulos)} rótulos en {(time.time() - inicio) / 60:.1f} min")

    DESTINO.write_text(
        json.dumps(
            [
                {
                    "inicio_s": r.inicio_s,
                    "fin_s": r.fin_s,
                    "lineas": r.lineas,
                    "confianza": r.confianza,
                    "apariciones": r.apariciones,
                }
                for r in rotulos
            ],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    for r in rotulos:
        log(f"  [{int(r.inicio_s) // 60:02d}:{int(r.inicio_s) % 60:02d}] {r.texto}")
    log("ROTULOS LISTOS")
