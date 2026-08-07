"""Valida la diarización REAL (ECAPA de speechbrain) sobre audio sintético.

Corre con:  pytest -m slow
Descarga el modelo de voz (~85 MB) la primera vez.

LÍMITE CONOCIDO DE ESTA PRUEBA: dos timbres sintéticos NO son dos personas.
Los embeddings de tonos artificiales caen todos juntos en una zona del
espacio donde las distancias son mucho menores que entre voces reales
(medido en esta máquina: <0.28 entre los dos "hablantes" de aquí, cuando dos
personas distintas suelen superar 0.6). Por eso se fija `n_hablantes`: lo que
se prueba es la CADENA (decodificar → embeber → agrupar → turnos), no la
calidad del umbral automático, que solo puede calibrarse con grabaciones
reales.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.slow


def _wav_dos_voces(ruta, plan, sr=16000):
    """Escribe un wav alternando dos timbres distintos según `plan`."""
    import av

    rng = np.random.default_rng(7)

    def timbre(f0, duracion):
        t = np.linspace(0, duracion, int(sr * duracion), endpoint=False)
        onda = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 9))
        onda *= 1 + 0.3 * np.sin(2 * np.pi * 5 * t)  # trémolo
        onda += 0.05 * rng.standard_normal(len(t))
        return onda / np.abs(onda).max() * 0.8

    total = np.concatenate(
        [timbre(110 if quien == "A" else 240, fin - ini) for quien, ini, fin in plan]
    )
    pcm = (total * 32767).astype(np.int16)
    with av.open(str(ruta), "w") as contenedor:
        stream = contenedor.add_stream("pcm_s16le", rate=sr)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.rate = sr
        for paquete in stream.encode(frame):
            contenedor.mux(paquete)
        for paquete in stream.encode(None):
            contenedor.mux(paquete)


def test_ecapa_separa_dos_voces_y_devuelve_turnos_absolutos(tmp_path):
    from videoindex.infrastructure.diarization.ecapa_provider import EcapaDiarizationProvider

    plan = [
        ("A", 0.0, 4.0),
        ("B", 4.0, 8.0),
        ("A", 8.0, 12.0),
        ("B", 12.0, 16.0),
        ("A", 16.0, 20.0),
        ("B", 20.0, 24.0),
    ]
    ruta = tmp_path / "dos_voces.wav"
    _wav_dos_voces(ruta, plan)
    regiones = [(ini, fin) for _, ini, fin in plan]

    turnos = EcapaDiarizationProvider(n_hablantes=2).diarizar(str(ruta), regiones)

    assert len(turnos) == 6  # ninguna región se fusiona: van alternadas
    assert [t.speaker for t in turnos] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ] * 3, "cada timbre debe caer siempre en el mismo grupo"
    # Timestamps absolutos sobre el archivo (ADR-002), no relativos al turno.
    assert turnos[0].start_time == 0.0
    assert turnos[-1].end_time == 24.0


def test_las_regiones_muy_cortas_no_rompen_la_diarizacion(tmp_path):
    """Una interjección de 0.2 s no da embedding fiable: se salta y el turno
    de quien habla a ambos lados no se parte."""
    from videoindex.infrastructure.diarization.ecapa_provider import EcapaDiarizationProvider

    plan = [("A", 0.0, 5.0), ("B", 5.0, 5.2), ("A", 5.2, 10.0)]
    ruta = tmp_path / "con_interjeccion.wav"
    _wav_dos_voces(ruta, plan)

    turnos = EcapaDiarizationProvider(n_hablantes=1).diarizar(
        str(ruta), [(ini, fin) for _, ini, fin in plan]
    )
    assert len(turnos) == 1
    assert (turnos[0].start_time, turnos[0].end_time) == (0.0, 10.0)


def test_audio_sin_pista_de_sonido_avisa(tmp_path):
    from videoindex.infrastructure.media.audio import cargar_audio_mono

    ruta = tmp_path / "vacio.txt"
    ruta.write_text("esto no es audio")
    with pytest.raises(Exception):  # noqa: B017 - PyAV lanza su propio tipo
        cargar_audio_mono(ruta)
