"""Estimación de tiempo de procesamiento — estándar del usuario:
mostrar ETA ANTES de procesar y recalibrar con lo medido.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TimeEstimator:
    # Horas de proceso por hora de video (whisper small, CPU int8).
    # Docstring de TarotCultural: 30-50 min/hora → factor inicial 0.5.
    factor: float = 0.5
    _muestras: int = 0

    def eta_segundos(self, duracion_video_s: float) -> float:
        return duracion_video_s * self.factor

    def eta_lote(self, duraciones_s: list[float]) -> float:
        return sum(self.eta_segundos(d) for d in duraciones_s)

    def calibrar(self, duracion_video_s: float, tiempo_real_s: float) -> None:
        """Media móvil: el factor converge al desempeño real de esta máquina."""
        if duracion_video_s <= 0:
            return
        observado = tiempo_real_s / duracion_video_s
        self._muestras += 1
        peso = 1.0 / self._muestras
        self.factor = (1 - peso) * self.factor + peso * observado

    @staticmethod
    def humano(segundos: float) -> str:
        m, s = divmod(int(segundos), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h} h {m} min"
        if m:
            return f"{m} min"
        return f"{s} s"
