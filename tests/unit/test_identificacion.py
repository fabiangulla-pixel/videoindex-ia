"""Identificación nominal: de "SPEAKER_01" a "CARLA ULLOA — HISTORIADORA".

Regla que vertebra estos tests: **es peor inventar un nombre que dejar una
voz sin identificar**. Varios casos comprueban justamente que el sistema NO
atribuye un nombre cuando la evidencia no da.
"""

from __future__ import annotations

from videoindex.application.identificacion_service import (
    ALTO,
    BAJO,
    MEDIO,
    _parece_nombre,
    _separar_cargo,
    identificar,
    interpretar_rotulo,
    menciones_verbales,
)
from videoindex.application.rotulos_service import Rotulo
from videoindex.domain.models import SpeakerTurn


def _rotulo(inicio, fin, lineas):
    return Rotulo(inicio_s=inicio, fin_s=fin, lineas=lineas, confianza=0.9, apariciones=5)


def test_la_tarjeta_de_una_cita_no_es_la_identificacion_de_nadie():
    """Caso real del documental: atribuirle a una voz el título de un libro
    y el nombre del autor citado sería un error grave en el documento final."""
    assert (
        interpretar_rotulo(_rotulo(0, 5, ["Confiesó que he vivido", "Pablo Neruda, 1974"])) is None
    )


def test_parece_nombre_distingue_nombres_de_frases_y_cargos():
    assert _parece_nombre("CARLA ULLOA")
    assert _parece_nombre("Juan de Dios Pérez")  # partículas de apellido, sí
    assert not _parece_nombre("HISTORIADORA")  # cargo
    assert not _parece_nombre("POETA INVESTIGADORA UNAM")  # cargo + institución
    assert not _parece_nombre("Confiesó que he vivido")  # frase
    assert not _parece_nombre("Pablo Neruda, 1974")  # pie de cita con año


def test_separar_cargo_extrae_la_institucion():
    assert _separar_cargo("POETA INVESTIGADORA UNAM") == ("POETA INVESTIGADORA", "UNAM")
    assert _separar_cargo("HISTORIADORA") == ("HISTORIADORA", None)


def test_rotulo_sobre_quien_habla_da_identificacion_de_confianza_alta():
    turnos = [SpeakerTurn(200.0, 260.0, "SPEAKER_01")]
    rotulos = [_rotulo(205.0, 211.0, ["CARLA ULLOA", "HISTORIADORA"])]

    identidad = identificar(turnos, rotulos)[0]
    assert identidad.nombre == "CARLA ULLOA"
    assert identidad.funcion == "HISTORIADORA"
    assert identidad.confianza == ALTO
    assert identidad.descriptor == "CARLA ULLOA — HISTORIADORA"
    assert "Rótulo en pantalla" in identidad.evidencias[0]


def test_el_rotulo_se_asigna_a_quien_mas_habla_en_esa_ventana():
    """Si el rótulo cae en un cruce, gana quien ocupa más tiempo, no quien
    empieza antes."""
    turnos = [
        SpeakerTurn(200.0, 202.0, "SPEAKER_00"),
        SpeakerTurn(202.0, 260.0, "SPEAKER_01"),
    ]
    identidades = {
        i.speaker_label: i
        for i in identificar(turnos, [_rotulo(205.0, 211.0, ["CARLA ULLOA", "HISTORIADORA"])])
    }
    assert identidades["SPEAKER_01"].nombre == "CARLA ULLOA"
    assert identidades["SPEAKER_00"].nombre is None


def test_sin_evidencia_no_se_inventa_nombre():
    turnos = [SpeakerTurn(0.0, 30.0, "SPEAKER_00")]
    identidad = identificar(turnos, [])[0]
    assert identidad.nombre is None
    assert identidad.confianza == BAJO
    assert identidad.etiqueta_editorial == "VOZ NO IDENTIFICADA"


def test_un_mismo_nombre_en_dos_voces_baja_la_confianza():
    """O la separación de voces partió a una persona en dos, o un rótulo se
    atribuyó mal. En cualquier caso no puede quedar como ALTO."""
    turnos = [
        SpeakerTurn(100.0, 160.0, "SPEAKER_00"),
        SpeakerTurn(400.0, 460.0, "SPEAKER_01"),
    ]
    rotulos = [
        _rotulo(105.0, 111.0, ["CARLA ULLOA", "HISTORIADORA"]),
        _rotulo(405.0, 411.0, ["CARLA ULLOA", "HISTORIADORA"]),
    ]
    identidades = identificar(turnos, rotulos)
    assert all(i.confianza == MEDIO for i in identidades)
    assert any("atribuido a 2 voces distintas" in e for i in identidades for e in i.evidencias)


def test_dos_rotulos_distintos_sobre_la_misma_voz_se_marcan_como_conflicto():
    turnos = [SpeakerTurn(100.0, 500.0, "SPEAKER_00")]
    rotulos = [
        _rotulo(105.0, 111.0, ["CARLA ULLOA", "HISTORIADORA"]),
        _rotulo(405.0, 411.0, ["HERNÁN BRAVO", "POETA ENSAYISTA"]),
    ]
    identidad = identificar(turnos, rotulos)[0]
    assert identidad.confianza == MEDIO
    assert any("CONFLICTO" in e for e in identidad.evidencias)


def test_menciones_verbales_detecta_formulas_de_presentacion():
    segmentos = [
        {"start": 10.0, "texto": "Bueno, mi nombre es Soledad Bianchi y trabajo en esto."},
        {"start": 50.0, "texto": "Hoy estamos con Hernán Bravo en su casa."},
        {"start": 90.0, "texto": "No hay ningún nombre en esta frase."},
    ]
    encontradas = menciones_verbales(segmentos)
    assert (10.0, "Soledad Bianchi") in encontradas
    assert (50.0, "Hernán Bravo") in encontradas
    assert len(encontradas) == 2


def test_una_mencion_verbal_sola_no_llega_a_confianza_alta():
    """Sin respaldo visual, oír un nombre no prueba que sea quien habla."""
    turnos = [SpeakerTurn(10.0, 40.0, "SPEAKER_00")]
    segmentos = [{"start": 12.0, "texto": "Hola, mi nombre es Soledad Bianchi."}]
    identidad = identificar(turnos, [], segmentos)[0]
    assert identidad.nombre == "Soledad Bianchi"
    assert identidad.confianza == MEDIO


def test_la_voz_que_habla_mucho_y_nunca_se_rotula_se_trata_como_voz_en_off():
    turnos = [
        SpeakerTurn(0.0, 120.0, "SPEAKER_00"),  # narra 2 min, sin rótulo
        SpeakerTurn(200.0, 260.0, "SPEAKER_01"),
    ]
    rotulos = [_rotulo(205.0, 211.0, ["CARLA ULLOA", "HISTORIADORA"])]
    identidades = {i.speaker_label: i for i in identificar(turnos, rotulos)}

    narrador = identidades["SPEAKER_00"]
    assert narrador.es_voz_en_off
    assert narrador.etiqueta_editorial == "VOZ EN OFF"
    assert narrador.descriptor == "VOZ EN OFF — NARRACIÓN"
    assert not identidades["SPEAKER_01"].es_voz_en_off


def test_una_voz_breve_sin_rotulo_no_se_declara_narracion():
    """Una intervención suelta de 20 s es un participante sin identificar,
    no el narrador del documental."""
    identidad = identificar([SpeakerTurn(0.0, 20.0, "SPEAKER_00")], [])[0]
    assert not identidad.es_voz_en_off
    assert identidad.etiqueta_editorial == "VOZ NO IDENTIFICADA"
