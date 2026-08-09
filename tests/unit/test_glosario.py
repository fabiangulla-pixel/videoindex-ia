"""Corrección de nombres propios contra el glosario del propio video.

Casi la mitad de estos tests comprueban que NO corrige. Reescribir lo que
alguien dijo es peor que dejar una errata, sobre todo en un texto publicado.

Los números vienen de medir pares reales, no de intuición: "Boliviano" se
parece a "Bolaño" (0.80) MÁS que "Bianqui" a "Bianchi" (0.71). Como las dos
clases se solapan, no hay umbral que las separe y por eso hay dos niveles:
se aplica solo la restauración de tildes, y lo demás se sugiere.
"""

from __future__ import annotations

from videoindex.domain.glosario import construir_glosario, corregir


def test_construir_glosario_parte_los_nombres_en_palabras():
    """En el audio se dice "Bianchi", no "Soledad Bianchi": hay que poder
    corregir el apellido suelto."""
    g = construir_glosario(["SOLEDAD BIANCHI", "Hernán Bravo"], ["Canto General"])
    assert {"BIANCHI", "SOLEDAD", "Hernán", "General", "Bravo", "Canto"} <= set(g)
    # Nada por debajo del mínimo: en palabras cortas, cambiar una letra las
    # convierte en otra palabra corriente.
    assert all(len(t) >= 5 for t in g)


# ---- lo que SÍ se aplica: tildes y mayúsculas ----------------------------


def test_restaura_la_enye_perdida():
    g = construir_glosario(["Roberto Bolaño"])
    r = corregir("¿Y Bolano? Sí, Bolano.", g)
    assert r.texto == "¿Y Bolaño? Sí, Bolaño."
    assert len(r.cambios) == 2


def test_restaura_tildes():
    g = construir_glosario(["Hernán Bravo"])
    assert corregir("dijo Hernan Bravo", g).texto == "dijo Hernán Bravo"


def test_respeta_mayusculas_del_original():
    g = construir_glosario(["Roberto Bolaño"])
    assert "BOLAÑO" in corregir("DIJO BOLANO", g).texto


def test_no_toca_lo_que_ya_esta_bien_escrito():
    g = construir_glosario(["Soledad Bianchi"])
    r = corregir("Como decía Bianchi en su ensayo", g)
    assert r.cambios == []
    assert r.texto == "Como decía Bianchi en su ensayo"


# ---- lo que solo se SUGIERE ---------------------------------------------


def test_una_variante_muy_cercana_se_sugiere_pero_no_se_aplica():
    """Cambiar letras es decisión humana: el texto sale intacto y el caso
    queda anotado para revisión."""
    g = construir_glosario(["Soledad Bianchi"])
    r = corregir("Como decía Bianchy en su ensayo", g)
    assert "Bianchy" in r.texto  # NO se aplicó
    assert r.cambios == []
    assert r.sugerencias[0].original == "Bianchy"
    assert r.sugerencias[0].corregido == "Bianchi"


def test_una_variante_fonetica_lejana_se_deja_pasar_en_silencio():
    """Compromiso asumido y medido: 'Bianqui' suena igual que 'Bianchi' pero
    solo se parecen un 0.71, la misma zona en la que viven los falsos
    positivos ('Boliviano'/'Bolaño' está en 0.80). Se prefiere perder esta
    sugerencia antes que llenar la lista de ruido que nadie revisaría."""
    g = construir_glosario(["Soledad Bianchi"])
    r = corregir("Como decía Bianqui en su ensayo", g)
    assert r.cambios == [] and r.sugerencias == []


def test_una_sugerencia_repetida_se_reporta_una_sola_vez():
    g = construir_glosario(["Soledad Bianchi"])
    r = corregir("Bianchy dijo. Y Bianchy insistió.", g)
    assert len(r.sugerencias) == 1


# ---- lo que NO se toca ni se sugiere -------------------------------------


def test_no_confunde_una_palabra_mas_larga_con_el_nombre():
    """Caso medido: 'Boliviano' se parece a 'Bolaño' más que 'Bianqui' a
    'Bianchi'. Lo descarta la diferencia de longitud, no la similitud."""
    g = construir_glosario(["Roberto Bolaño"])
    r = corregir("el escritor boliviano llegó a México", g)
    assert r.cambios == []
    assert r.sugerencias == []
    assert "boliviano" in r.texto


def test_no_reescribe_palabras_distintas_aunque_empiecen_igual():
    g = construir_glosario(["Soledad Bianchi"])
    for frase in ("El caballo blanco", "fue al banco central"):
        r = corregir(frase, g)
        assert r.cambios == [] and r.sugerencias == [], frase


def test_no_toca_palabras_cortas():
    g = construir_glosario(["Kemy Oyarzún"])
    r = corregir("pero como cosa rara", g)
    assert r.cambios == [] and r.sugerencias == []


def test_glosario_vacio_no_cambia_nada():
    r = corregir("texto cualquiera", [])
    assert r.texto == "texto cualquiera"
    assert r.cambios == [] and r.sugerencias == []


def test_no_confunde_dos_nombres_del_glosario_entre_si():
    """Con varios términos parecidos gana el más cercano, no el primero."""
    g = construir_glosario(["Gabriela Mistral", "Gabriel García"])
    r = corregir("la poeta Gabriella escribió", g)
    assert r.sugerencias[0].corregido == "Gabriela"


# ---- regresiones del material real ---------------------------------------


def test_no_capitaliza_palabras_comunes_que_estan_en_un_titulo():
    """Caso real que habría estropeado el texto: 'Los Detectives Salvajes'
    está en el glosario, y eso convertía 'los detectives salvajes' de la
    prosa corriente en un título, y 'en general' en 'en General'."""
    g = construir_glosario([], ["Los Detectives Salvajes", "Canto General"])
    r = corregir("hablaba de los detectives salvajes en general", g)
    assert r.cambios == []
    assert r.texto == "hablaba de los detectives salvajes en general"


def test_no_convierte_un_nombre_bien_escrito_a_mayusculas():
    """El rótulo dice 'GONZÁLEZ' porque los rótulos van en caja alta; eso no
    significa que en el texto haya que gritar el apellido."""
    g = construir_glosario(["SANDRA IVETTE GONZÁLEZ"])
    r = corregir("según González, la poesía", g)
    assert r.cambios == []
    assert "González" in r.texto


def test_restaura_la_tilde_respetando_la_caja_original():
    g = construir_glosario(["Roberto Bolaño"])
    assert corregir("de bolano", g).texto == "de bolaño"  # minúscula se queda
    assert corregir("de Bolano", g).texto == "de Bolaño"
    assert corregir("DE BOLANO", g).texto == "DE BOLAÑO"


def test_no_sugiere_sobre_palabras_comunes_en_minuscula():
    """Con el umbral viejo salían 'blanco'→'Bolaño' y 'camino'→'Canto'."""
    g = construir_glosario(["Roberto Bolaño"], ["Canto General"])
    r = corregir("el caballo blanco iba de camino", g)
    assert r.sugerencias == []
