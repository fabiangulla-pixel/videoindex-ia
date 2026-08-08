"""Fixtures compartidas: BD en memoria y fakes deterministas (sin modelos)."""

from __future__ import annotations

import hashlib

import pytest

from videoindex.domain.models import TranscriptSegment
from videoindex.infrastructure.db.connection import conectar


@pytest.fixture
def con():
    con = conectar(":memory:")
    yield con
    con.close()


class FakeEmbeddingProvider:
    """Determinista y barato: hash del texto → vector pseudo-aleatorio normalizado.

    Textos iguales → vectores iguales; textos que comparten prefijo largo pueden
    controlarse en tests usando textos idénticos o totalmente distintos.
    """

    model_name = "fake-model"
    dimensions = 8

    def encode(self, textos: list[str]) -> list[list[float]]:
        out = []
        for t in textos:
            h = hashlib.sha256(t.encode()).digest()
            v = [b / 255.0 - 0.5 for b in h[: self.dimensions]]
            norma = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norma for x in v])
        return out


class FakeNERProvider:
    """Extrae como 'persona' toda palabra capitalizada de ≥4 letras."""

    def extraer(self, texto: str) -> list[tuple[str, str]]:
        vistos = set()
        out = []
        for palabra in texto.split():
            p = palabra.strip(".,;:¿?¡!()\"'")
            if len(p) >= 4 and p[0].isupper() and p.lower() not in vistos:
                vistos.add(p.lower())
                out.append((p, "persona"))
        return out


class FakeTranscriptionProvider:
    """Devuelve segmentos fijos; puede fallar en rutas marcadas.

    Respeta el contrato completo del puerto: `desde_s` filtra lo ya
    transcrito (como haría clip_timestamps) y `al_segmento` va emitiendo
    cada segmento, que es lo que permite persistir de forma incremental.
    `morir_tras` simula que el proceso se corta a mitad.
    """

    def __init__(
        self,
        segmentos_por_ruta: dict[str, list[TranscriptSegment]] | None = None,
        fallar_en: set[str] | None = None,
        morir_tras: int | None = None,
    ):
        self.segmentos_por_ruta = segmentos_por_ruta or {}
        self.fallar_en = fallar_en or set()
        self.morir_tras = morir_tras
        self.llamadas: list[str] = []
        self.reanudaciones: list[float] = []

    def transcribir(
        self,
        ruta_video: str,
        video_id: str,
        progreso=None,
        desde_s: float = 0.0,
        al_segmento=None,
    ) -> list[TranscriptSegment]:
        self.llamadas.append(ruta_video)
        self.reanudaciones.append(desde_s)
        if ruta_video in self.fallar_en:
            raise RuntimeError(f"fallo simulado en {ruta_video}")
        emitidos = []
        for s in self.segmentos_por_ruta.get(ruta_video, []):
            if s.start_time < desde_s:
                continue  # ya estaba transcrito
            s.video_id = video_id
            if self.morir_tras is not None and len(emitidos) >= self.morir_tras:
                raise RuntimeError("proceso interrumpido (simulado)")
            emitidos.append(s)
            if al_segmento:
                al_segmento(s)
        if progreso:
            progreso(1.0)
        return emitidos


@pytest.fixture
def fake_embedder():
    return FakeEmbeddingProvider()


@pytest.fixture
def fake_ner():
    return FakeNERProvider()


def hacer_segmentos(
    video_id: str, textos_y_tiempos: list[tuple[str, float, float]], confidence: float = 0.9
) -> list[TranscriptSegment]:
    from uuid import uuid4

    return [
        TranscriptSegment(
            segment_id=str(uuid4()),
            video_id=video_id,
            start_time=ini,
            end_time=fin,
            raw_text=txt,
            clean_text=txt,
            confidence=confidence,
        )
        for txt, ini, fin in textos_y_tiempos
    ]
