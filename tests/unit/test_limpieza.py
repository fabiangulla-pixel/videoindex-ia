"""Limpieza de lectura: quitar ruido del habla SIN alterar lo dicho."""

from __future__ import annotations

from videoindex.domain.limpieza import limpiar_para_lectura


def test_quita_interjecciones_de_vacilacion():
    assert limpiar_para_lectura("Eh, yo creo que sí") == "Yo creo que sí"
    assert limpiar_para_lectura("Bueno mm es complicado") == "Bueno es complicado"


def test_quita_repeticiones_inmediatas():
    assert limpiar_para_lectura("la la casa de mi madre") == "La casa de mi madre"
    assert limpiar_para_lectura("que que yo sepa") == "Que yo sepa"


def test_no_toca_palabras_con_contenido():
    """'este' es demostrativo y 'o sea' articula el argumento: borrarlos
    cambiaría lo que la persona dijo."""
    texto = "Este autor, o sea, el que citábamos antes, digamos que acertó"
    assert limpiar_para_lectura(texto) == texto


def test_no_recorta_palabras_que_contienen_una_muletilla():
    """'eh' dentro de otra palabra no es una vacilación."""
    assert "vehículo" in limpiar_para_lectura("El vehículo llegó")
    assert limpiar_para_lectura("Ahora empezamos") == "Ahora empezamos"


def test_arregla_espaciado_y_puntuacion_duplicada():
    assert limpiar_para_lectura("Hola  ,  mundo..") == "Hola, mundo."
    assert limpiar_para_lectura("  texto suelto  ") == "Texto suelto"


def test_es_idempotente():
    """Aplicarla dos veces no puede seguir comiéndose texto."""
    texto = "Eh, la la verdad es que  , sí"
    una = limpiar_para_lectura(texto)
    assert limpiar_para_lectura(una) == una


def test_texto_vacio_no_revienta():
    assert limpiar_para_lectura("") == ""
    assert limpiar_para_lectura("   ") == ""
    assert limpiar_para_lectura("eh") == ""
