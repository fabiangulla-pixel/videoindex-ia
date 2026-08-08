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
from collections.abc import Callable
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

    def transcribir(
        self,
        ruta_video: str,
        video_id: str,
        progreso: Callable[[float], None] | None = None,
        desde_s: float = 0.0,
        al_segmento: Callable[[TranscriptSegment], None] | None = None,
    ) -> list[TranscriptSegment]:
        """progreso(fraccion): avance real dentro de ESTE video, calculado
        como seg.end / duración total (faster-whisper no expone un % nativo;
        los segmentos SÍ traen timestamp absoluto conforme se van generando,
        así que se deriva de ahí en vez de solo reportar por-video del lote).

        desde_s > 0 reanuda una transcripción interrumpida. Se pasa como
        `clip_timestamps`, que recorta el tramo a procesar pero **mantiene
        los timestamps referidos al archivo completo** (verificado sobre
        material real: con desde_s=600 el primer segmento vuelve con
        start=600.0, no con start=0.0), así que ADR-002 se respeta.
        """
        model = _modelo(self.nombre_modelo, self.compute_type)
        opciones = {}
        if desde_s > 0:
            opciones["clip_timestamps"] = [float(desde_s)]
        segments, info = model.transcribe(
            ruta_video,
            language=self.idioma,
            vad_filter=True,
            beam_size=self.beam_size,
            initial_prompt=self.initial_prompt or None,
            condition_on_previous_text=self.condition_on_previous_text,
            **opciones,
        )
        duracion_total = info.duration or 0.0
        resultado: list[TranscriptSegment] = []
        for seg in segments:
            if progreso and duracion_total > 0:
                progreso(min(1.0, seg.end / duracion_total))
            texto = seg.text.strip()
            if not texto:
                continue
            # avg_logprob es <= 0; 0.0 es el mejor caso posible (exp(0)=1.0),
            # así que se compara contra None, no con la verdad booleana de 0.0.
            confianza = min(1.0, math.exp(seg.avg_logprob)) if seg.avg_logprob is not None else 0.0
            segmento = TranscriptSegment(
                segment_id=str(uuid4()),
                video_id=video_id,
                start_time=float(seg.start),
                end_time=float(seg.end),
                raw_text=seg.text,  # inmutable, tal como salió de Whisper
                clean_text=texto,
                confidence=confianza,
            )
            resultado.append(segmento)
            if al_segmento:
                al_segmento(segmento)
        return resultado
