"""Transcripción local con faster-whisper ($0, sin API externa).

Adaptado de TarotCultural corpus_pipeline/transcribir.py. Cambios:
- Devuelve TranscriptSegment del dominio con timestamps ABSOLUTOS en segundos
  (faster-whisper ya los da absolutos sobre el archivo completo — ADR-002).
- Captura confidence = exp(avg_logprob) acotado a [0,1].
- compute_type="int8" explícito: lo más rápido en CPU sin GPU.
- No requiere ffmpeg: PyAV decodifica el audio del video.
"""

from __future__ import annotations

import math
from functools import lru_cache
from uuid import uuid4

from videoindex.domain.models import TranscriptSegment


@lru_cache(maxsize=1)
def _modelo(nombre: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(nombre, device="auto", compute_type=compute_type)


class FasterWhisperProvider:
    def __init__(
        self,
        modelo: str = "small",
        idioma: str = "es",
        compute_type: str = "int8",
        beam_size: int = 5,
        initial_prompt: str = "",
        condition_on_previous_text: bool = True,
    ):
        self.nombre_modelo = modelo
        self.idioma = idioma
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt
        self.condition_on_previous_text = condition_on_previous_text

    def transcribir(self, ruta_video: str, video_id: str) -> list[TranscriptSegment]:
        model = _modelo(self.nombre_modelo, self.compute_type)
        segments, _info = model.transcribe(
            ruta_video,
            language=self.idioma,
            vad_filter=True,
            beam_size=self.beam_size,
            initial_prompt=self.initial_prompt or None,
            condition_on_previous_text=self.condition_on_previous_text,
        )
        resultado: list[TranscriptSegment] = []
        for seg in segments:
            texto = seg.text.strip()
            if not texto:
                continue
            # avg_logprob es <= 0; 0.0 es el mejor caso posible (exp(0)=1.0),
            # así que se compara contra None, no con la verdad booleana de 0.0.
            confianza = min(1.0, math.exp(seg.avg_logprob)) if seg.avg_logprob is not None else 0.0
            resultado.append(
                TranscriptSegment(
                    segment_id=str(uuid4()),
                    video_id=video_id,
                    start_time=float(seg.start),
                    end_time=float(seg.end),
                    raw_text=seg.text,  # inmutable, tal como salió de Whisper
                    clean_text=texto,
                    confidence=confianza,
                )
            )
        return resultado
