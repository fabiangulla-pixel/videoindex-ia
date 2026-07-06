"""Fusión híbrida: casos calculados a mano."""

from videoindex.domain.fusion import PesosFusion, fusionar, fusionar_rrf, normalizar_minmax


def test_pesos_default_suman_uno():
    p = PesosFusion()
    assert abs(p.semantico + p.textual + p.entidades + p.confianza - 1.0) < 1e-9


def test_minmax_normal():
    scores = {"a": 0.2, "b": 0.6, "c": 1.0}
    norm = normalizar_minmax(scores)
    assert norm["a"] == 0.0 and norm["c"] == 1.0
    assert abs(norm["b"] - 0.5) < 1e-9


def test_minmax_invertido_bm25():
    # BM25 de SQLite: negativo, menor = mejor. -8 debe quedar mejor que -2.
    norm = normalizar_minmax({"peor": -2.0, "mejor": -8.0}, invertir=True)
    assert norm["mejor"] == 1.0 and norm["peor"] == 0.0


def test_minmax_valores_iguales_valen_uno():
    assert normalizar_minmax({"a": 0.5, "b": 0.5}) == {"a": 1.0, "b": 1.0}
    assert normalizar_minmax({"solo": -3.0}, invertir=True) == {"solo": 1.0}


def test_minmax_vacio():
    assert normalizar_minmax({}) == {}


def test_fusion_calculada_a_mano():
    # a: top semántico y textual; b: solo textual bueno.
    resultado = fusionar(
        semanticos={"a": 0.9, "b": 0.1},
        textuales_bm25={"a": -5.0, "b": -3.0},
        entidades={"a": 1.0},
        confianzas={"a": 0.8, "b": 0.6},
    )
    scores = {cid: s for cid, s, _ in resultado}
    # a: 0.45*1 + 0.30*1 + 0.15*1 + 0.10*0.8 = 0.98
    assert abs(scores["a"] - 0.98) < 1e-9
    # b: 0.45*0 + 0.30*0 + 0.15*0 + 0.10*0.6 = 0.06
    assert abs(scores["b"] - 0.06) < 1e-9
    assert resultado[0][0] == "a"


def test_fusion_chunk_ausente_en_una_fuente_aporta_cero():
    resultado = fusionar(
        semanticos={"a": 0.9},
        textuales_bm25={"b": -3.0},
        entidades={},
        confianzas={},
    )
    desglose = {cid: b for cid, _, b in resultado}
    assert desglose["a"].textual == 0.0
    assert desglose["b"].semantico == 0.0


def test_rrf_referencia():
    resultado = fusionar_rrf([["a", "b", "c"], ["b", "a", "c"]], k=60)
    orden = [cid for cid, _ in resultado]
    # a y b empatan casi; c es último siempre.
    assert orden[-1] == "c"
