"""TranscriptionSettings: defaults nuevos = comportamiento actual de
faster-whisper, para no cambiar nada a quien no los toque explícitamente."""

from videoindex.config.settings import TranscriptionSettings
from videoindex.infrastructure.transcription.faster_whisper_provider import (
    FasterWhisperProvider,
)


def test_defaults_iguales_a_faster_whisper():
    s = TranscriptionSettings()
    assert s.beam_size == 5
    assert s.initial_prompt == ""
    assert s.condition_on_previous_text is True


def test_provider_acepta_solo_3_posicionales_sin_romper():
    # Firma histórica usada hoy por workers.py/cli.py antes de esta feature.
    p = FasterWhisperProvider("small", "es", "int8")
    assert p.beam_size == 5
    assert p.initial_prompt == ""
    assert p.condition_on_previous_text is True


def test_provider_acepta_los_3_parametros_nuevos():
    p = FasterWhisperProvider(
        "small",
        "es",
        "int8",
        beam_size=1,
        initial_prompt="vocabulario técnico: RAG, embeddings",
        condition_on_previous_text=False,
    )
    assert p.beam_size == 1
    assert p.initial_prompt == "vocabulario técnico: RAG, embeddings"
    assert p.condition_on_previous_text is False
