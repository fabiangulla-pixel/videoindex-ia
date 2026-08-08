"""Detección de lo que Whisper se inventa cuando no hay habla.

El caso que motivó el módulo es real: la transcripción de un documental sobre
literatura chilena terminaba con «Gracias por ver el video. Gracias por ver
el video.», atribuido a Gabriela Mistral.

La otra mitad de los tests importa igual: **no marcar habla real**. Un falso
positivo borra algo que alguien dijo de verdad.
"""

from __future__ import annotations

from videoindex.domain.alucinaciones import es_alucinacion_probable, es_repeticion_en_bucle


def test_coletilla_de_youtube_al_final_del_audio():
    assert es_alucinacion_probable("Gracias por ver el video. Gracias por ver el video.")
    assert es_alucinacion_probable("¡Suscríbete al canal!")
    assert es_alucinacion_probable("Subtítulos realizados por la comunidad de Amara.org")


def test_repeticion_en_bucle():
    assert es_repeticion_en_bucle("Sí, claro. Sí, claro.")
    assert es_repeticion_en_bucle("Música. Música. Música.")
    assert not es_repeticion_en_bucle("Una sola frase sin repetir.")


def test_una_frase_larga_repetida_es_retorica_no_alucinacion():
    """Repetir una oración larga y compleja es un recurso de un orador."""
    frase = (
        "La literatura chilena en el exilio mexicano se reinventa a sí misma "
        "cada vez que cruza la frontera."
    )
    assert not es_repeticion_en_bucle(f"{frase} {frase}")


def test_no_marca_habla_real():
    reales = [
        "Fueron las mujeres feministas las organizadas para atacar el orden de las cosas.",
        "Roberto Bolaño fue un escritor que se convirtió de pronto en un mito.",
        "Gracias.",
        "Sí.",
        "",
    ]
    for texto in reales:
        assert not es_alucinacion_probable(texto), texto


def test_una_mencion_de_paso_no_descarta_la_intervencion():
    """Si alguien dice la coletilla dentro de una intervención larga y real,
    la intervención se queda: solo se descarta si la coletilla ES el pasaje."""
    texto = (
        "Cuando subimos el documental a la plataforma pusimos al final eso de "
        "gracias por ver el video, que a mí me parecía una cursilería, pero el "
        "productor insistió en que había que ponerlo igual."
    )
    assert not es_alucinacion_probable(texto)


def test_las_intervenciones_alucinadas_no_entran_al_documento_pero_se_reportan(tmp_path):
    """No se borra nada en silencio: lo omitido va a incertidumbres.md."""
    from uuid import uuid4

    from videoindex.application.entrega_editorial import (
        Contexto,
        alucinaciones_descartadas,
        construir_intervenciones,
    )
    from videoindex.domain.models import TranscriptSegment

    def seg(inicio, fin, texto):
        return TranscriptSegment(str(uuid4()), "v", inicio, fin, texto, texto, 0.9, "SPEAKER_00")

    segmentos = [
        seg(0.0, 20.0, "El exilio marcó a toda una generación de escritores."),
        seg(600.0, 610.0, "Gracias por ver el video. Gracias por ver el video."),
    ]
    cuerpo = construir_intervenciones(segmentos)
    descartadas = alucinaciones_descartadas(segmentos)

    assert len(cuerpo) == 1
    assert "Gracias por ver el video" not in cuerpo[0].texto
    assert len(descartadas) == 1
    assert descartadas[0].start_time == 600.0

    from videoindex.application.entrega_editorial import escribir_incertidumbres

    ruta, asuntos = escribir_incertidumbres(tmp_path / "inc.md", [], [], segmentos, descartadas)
    texto = ruta.read_text(encoding="utf-8")
    assert "parecer inventados por el modelo" in texto
    assert "Gracias por ver el video" in texto  # se puede comprobar en el audio
    assert asuntos >= 1
    assert Contexto  # el paquete completo también las anota en proceso_tecnico
