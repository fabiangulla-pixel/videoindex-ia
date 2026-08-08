"""Diarización local con embeddings de voz ECAPA-TDNN ($0, sin API).

Por qué ECAPA + agrupamiento y no pyannote, que es el estándar: el pipeline
`pyannote/speaker-diarization-3.1` depende de `pyannote/segmentation-3.0`,
un modelo *gated* en Hugging Face (devuelve 401 sin token y sin aceptar sus
condiciones en la web). Eso rompe la promesa de "descarga y funciona" y la
de 100 % local sin cuentas. `speechbrain/spkrec-ecapa-voxceleb` es abierto.

Qué hace, y qué NO hace:
- Aprovecha que Whisper ya corrió su VAD: las regiones que llegan son tramos
  con voz. Aquí solo se decide QUIÉN habla en cada uno — un embedding de voz
  por región y agrupamiento por distancia coseno.
- NO detecta habla superpuesta (dos personas a la vez): esa región se le
  atribuye a una sola voz. Es la limitación real frente a pyannote y hay que
  tenerla en cuenta al revisar una discusión cruzada.
- NO identifica personas: distingue voces DENTRO de una grabación. Ponerles
  nombre es trabajo humano (ver SpeakerRepo).

Fijar el número de hablantes cuando se conoce (una entrevista son 2) es
bastante más fiable que dejar el umbral automático.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import lru_cache

import numpy as np

from videoindex.domain.diarization import renombrar_por_aparicion, turnos_desde_etiquetas
from videoindex.domain.models import SpeakerTurn
from videoindex.infrastructure.media.audio import SAMPLE_RATE, cargar_audio_mono, tramo

log = logging.getLogger(__name__)

MODELO_ECAPA = "speechbrain/spkrec-ecapa-voxceleb"
# Un embedding de voz no mejora por escuchar más de unos segundos; recortar
# acota la memoria en intervenciones muy largas (una clase magistral puede
# tener segmentos de minutos si el VAD no encontró pausas).
MAX_SEGUNDOS_POR_REGION = 30.0
LOTE = 8


@lru_cache(maxsize=1)
def _codificador(nombre_modelo: str):
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    from videoindex.config import paths

    paths.ensure_dirs()
    destino = paths.MODELOS_DIR / "ecapa"
    # local_strategy=COPY: por defecto speechbrain enlaza con symlinks, que en
    # Windows exigen privilegios elevados (avisa él mismo) y encima no
    # sobreviven a copiar la carpeta portable a otro PC.
    opciones = {
        "source": nombre_modelo,
        "savedir": str(destino),
        "run_opts": {"device": "cpu"},
        "local_strategy": LocalStrategy.COPY,
    }
    try:
        # Mismo bug que en local_embeddings.py: con el modelo ya en caché, un
        # HEAD request al Hub que falle (sin internet, firewall, .exe sin
        # certificados) aborta en vez de usar lo descargado.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        return EncoderClassifier.from_hparams(**opciones)
    except Exception:
        os.environ.pop("HF_HUB_OFFLINE", None)
        return EncoderClassifier.from_hparams(**opciones)


class EcapaDiarizationProvider:
    def __init__(
        self,
        modelo: str = MODELO_ECAPA,
        n_hablantes: int = 0,
        umbral_distancia: float = 0.75,
        duracion_minima_s: float = 0.6,
    ):
        self.modelo = modelo
        self.n_hablantes = n_hablantes
        self.umbral_distancia = umbral_distancia
        self.duracion_minima_s = duracion_minima_s

    def diarizar(
        self,
        ruta_media: str,
        regiones: list[tuple[float, float]],
        progreso: Callable[[float], None] | None = None,
    ) -> list[SpeakerTurn]:
        if not regiones:
            return []
        audio = cargar_audio_mono(ruta_media)
        if len(audio) == 0:
            return []

        indices, formas_onda = self._recortar_regiones(audio, regiones)
        if not indices:
            log.info("Ninguna región supera %.2fs: sin diarización", self.duracion_minima_s)
            return []

        vectores = self._embeddings(formas_onda, progreso)
        grupos = self._agrupar(vectores)

        etiquetas: list[str | None] = [None] * len(regiones)
        for posicion, indice_region in enumerate(indices):
            etiquetas[indice_region] = f"c{grupos[posicion]}"
        return renombrar_por_aparicion(turnos_desde_etiquetas(regiones, etiquetas))

    def _recortar_regiones(
        self, audio: np.ndarray, regiones: list[tuple[float, float]]
    ) -> tuple[list[int], list[np.ndarray]]:
        """Las regiones demasiado cortas para un embedding fiable se dejan
        fuera (quedan sin etiqueta y heredan hablante al asignar)."""
        indices: list[int] = []
        ondas: list[np.ndarray] = []
        for i, (inicio, fin) in enumerate(regiones):
            if fin - inicio < self.duracion_minima_s:
                continue
            onda = tramo(audio, inicio, min(fin, inicio + MAX_SEGUNDOS_POR_REGION))
            if len(onda) < int(self.duracion_minima_s * SAMPLE_RATE):
                continue  # la región cae fuera del audio real
            indices.append(i)
            ondas.append(onda)
        return indices, ondas

    def _embeddings(
        self, ondas: list[np.ndarray], progreso: Callable[[float], None] | None
    ) -> np.ndarray:
        """Un vector de voz por región, normalizado (norma 1) para que la
        distancia coseno del agrupamiento sea comparable entre pares."""
        import torch

        codificador = _codificador(self.modelo)
        salidas: list[np.ndarray] = []
        for inicio in range(0, len(ondas), LOTE):
            lote = ondas[inicio : inicio + LOTE]
            largo_max = max(len(o) for o in lote)
            relleno = np.zeros((len(lote), largo_max), dtype=np.float32)
            for fila, onda in enumerate(lote):
                relleno[fila, : len(onda)] = onda
            # wav_lens = longitud RELATIVA real de cada fila: sin esto el
            # pooling estadístico de ECAPA promediaría también el relleno y
            # los vectores de las regiones cortas saldrían sesgados.
            longitudes = torch.tensor([len(o) / largo_max for o in lote], dtype=torch.float32)
            with torch.no_grad():
                emb = codificador.encode_batch(torch.from_numpy(relleno), longitudes)
            salidas.append(emb.squeeze(1).cpu().numpy())
            if progreso:
                progreso(min(1.0, (inicio + len(lote)) / len(ondas)))

        vectores = np.concatenate(salidas).astype(np.float32)
        normas = np.linalg.norm(vectores, axis=1, keepdims=True)
        return vectores / np.maximum(normas, 1e-10)

    def _agrupar(self, vectores: np.ndarray) -> np.ndarray:
        """Agrupamiento jerárquico aglomerativo con enlace promedio.

        Con `n_hablantes` fijado se pide ese número exacto de grupos; en
        automático se corta por `umbral_distancia`, que es una heurística y
        está expuesta en la GUI justamente porque depende de la grabación
        (micrófono único vs. varios, ruido, voces parecidas).

        OJO con validarlo solo con audio sintético: los embeddings de tonos
        artificiales caen todos juntos en una zona del espacio donde las
        distancias no se parecen a las de voz real (medido: dos "voces"
        sintéticas quedan a <0.28 entre sí, cuando dos personas distintas
        suelen pasar de 0.6). Con material sintético, fijar n_hablantes."""
        from sklearn.cluster import AgglomerativeClustering

        if len(vectores) == 1:
            return np.zeros(1, dtype=int)

        if self.n_hablantes > 0:
            n = min(self.n_hablantes, len(vectores))
            agrupador = AgglomerativeClustering(n_clusters=n, metric="cosine", linkage="average")
        else:
            agrupador = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=self.umbral_distancia,
                metric="cosine",
                linkage="average",
            )
        return agrupador.fit_predict(vectores)


def crear_diarizador(cfg) -> EcapaDiarizationProvider | None:
    """Diarizador según DiarizationSettings, o None si está desactivada.

    Devolver None (en vez de un objeto que no hace nada) deja el pipeline
    con una condición explícita: sin diarizador no se ejecuta la etapa ni se
    pierde tiempo decodificando el audio.
    """
    if not cfg.activa:
        return None
    return EcapaDiarizationProvider(
        modelo=cfg.modelo,
        n_hablantes=cfg.n_hablantes,
        umbral_distancia=cfg.umbral_distancia,
        duracion_minima_s=cfg.duracion_minima_s,
    )
