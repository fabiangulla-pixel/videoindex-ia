from videoindex.domain.discourse import clasificar


def test_definicion():
    assert clasificar("El embedding se define como un vector denso.") == "definicion"


def test_ejemplo():
    assert clasificar("Por ejemplo, si tomamos las casas de Bogotá...") == "ejemplo"


def test_resumen():
    assert clasificar("En resumen, vimos tres modelos hoy.") == "resumen"


def test_pregunta_por_densidad():
    texto = "¿Alguien sabe? ¿Qué pasa aquí? ¿Por qué falla?"
    assert clasificar(texto) == "pregunta"


def test_default_exposicion():
    assert clasificar("El modelo se entrena con descenso de gradiente.") == "exposicion"
