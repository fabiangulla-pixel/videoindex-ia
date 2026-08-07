"""Consenso temporal de rótulos: convertir OCR ruidoso en texto fiable.

Los casos de aquí son REALES, medidos sobre el documental "Estravagario":
el mismo rótulo se leyó "SOLEDAD BIANCHI", "%LEDAD BIANCHI", "IANCHI" y
"TE SOLEDAD BIANCHI" en fotogramas distintos. Cada test fija una de las
decisiones que hicieron falta para reconstruir el texto correcto.
"""

from __future__ import annotations

from videoindex.application.rotulos_service import (
    _consenso,
    _limpiar_bordes,
    normalizar,
)


def test_normalizar_ignora_tildes_mayusculas_y_puntuacion():
    assert normalizar("Hernán Bravo") == "HERNAN BRAVO"
    assert normalizar("POETA, NOVELISTA") == "POETA  NOVELISTA".replace("  ", " ")
    assert normalizar("  ") == ""


def test_limpiar_bordes_quita_ruido_pegado_a_los_extremos():
    """Caso real: un adorno del gráfico se leía como 'TE' delante del nombre."""
    assert _limpiar_bordes("TE SOLEDAD BIANCHI") == "SOLEDAD BIANCHI"
    assert _limpiar_bordes("CARLA ULLOA |") == "CARLA ULLOA"
    # Dentro de la línea, un token corto puede ser legítimo.
    assert _limpiar_bordes("POETA Y ENSAYISTA") == "POETA Y ENSAYISTA"


def test_consenso_reconstruye_el_nombre_completo_pese_a_lecturas_parciales():
    """La variante MÁS LARGA gana (la parcial es texto que falta), y después
    se le limpian los bordes (el ruido es texto añadido y corto)."""
    lecturas = [
        (290.0, "SOLEDAD BIANCHI", 0.92, 10),
        (291.0, "TE SOLEDAD BIANCHI", 0.85, 10),
        (292.0, "IANCHI", 0.83, 10),
        (293.0, "SOLEDAD BIANCHI", 0.91, 10),
    ]
    rotulos = _consenso(lecturas)
    assert len(rotulos) == 1
    assert rotulos[0].lineas == ["SOLEDAD BIANCHI"]
    assert rotulos[0].apariciones == 4  # la familia entera cuenta


def test_consenso_prefiere_la_lectura_completa_sobre_la_mas_frecuente():
    """Regresión: quedarse con la más repetida devolvía 'ULLOA' en vez de
    'CARLA ULLOA', porque la lectura incompleta sale más veces."""
    lecturas = [
        (205.0, "ULLOA", 0.92, 10),
        (206.0, "ULLOA", 0.92, 10),
        (207.0, "CARLA ULLOA", 0.89, 10),
        (208.0, "ULLOA", 0.90, 10),
    ]
    assert _consenso(lecturas)[0].lineas == ["CARLA ULLOA"]


def test_una_lectura_aislada_se_descarta_por_ruido():
    """El OCR sobre una textura produce cadenas que nunca se repiten."""
    assert _consenso([(100.0, "XKQ mn", 0.75, 10)]) == []


def test_dos_lineas_del_mismo_rotulo_se_ordenan_de_arriba_abajo():
    """El nombre va sobre el cargo: perder ese orden sería perder cuál es cuál."""
    lecturas = [
        (100.0, "POETA ENSAYISTA", 0.9, 250),
        (100.0, "HERNÁN BRAVO", 0.9, 200),
        (101.0, "POETA ENSAYISTA", 0.9, 250),
        (101.0, "HERNÁN BRAVO", 0.9, 200),
    ]
    assert _consenso(lecturas)[0].lineas == ["HERNÁN BRAVO", "POETA ENSAYISTA"]


def test_rotulos_separados_en_el_tiempo_no_se_mezclan():
    lecturas = [
        (100.0, "CARLA ULLOA", 0.9, 10),
        (101.0, "CARLA ULLOA", 0.9, 10),
        (400.0, "HERNÁN BRAVO", 0.9, 10),
        (401.0, "HERNÁN BRAVO", 0.9, 10),
    ]
    rotulos = _consenso(lecturas)
    assert [r.texto for r in rotulos] == ["CARLA ULLOA", "HERNÁN BRAVO"]
    assert rotulos[0].fin_s == 101.0 and rotulos[1].inicio_s == 400.0


def test_el_rotulo_puede_parpadear_sin_partirse_en_dos():
    """Un rótulo deja de leerse un par de fotogramas y vuelve: sigue siendo
    el mismo, no dos apariciones distintas."""
    lecturas = [(100.0, "CARLA ULLOA", 0.9, 10), (104.0, "CARLA ULLOA", 0.9, 10)]
    assert len(_consenso(lecturas)) == 1
