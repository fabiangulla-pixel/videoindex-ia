"""NER con spaCy — camino spaCy de Bashkar core/ner_engine.py, sin RoBERTa.

Mantiene el .exe liviano y la indexación 100 % local $0. El pipeline híbrido
con RoBERTa/LLM queda como evolución (la interfaz NERProvider no cambia).
"""

from __future__ import annotations

_SPACY_MAP = {
    "PER": "persona",
    "PERSON": "persona",
    "LOC": "lugar",
    "GPE": "lugar",
    "ORG": "organizacion",
    "MISC": "otro",
}

_MIN_LARGO = 3  # descarta siglas ruidosas de una o dos letras


class SpacyNERProvider:
    def __init__(self, nlp=None):
        self._nlp = nlp

    def _cargar(self):
        if self._nlp is None:
            from videoindex.infrastructure.ner.spacy_loader import cargar_modelo_es

            self._nlp = cargar_modelo_es()
        return self._nlp

    def extraer(self, texto: str) -> list[tuple[str, str]]:
        nlp = self._cargar()
        doc = nlp(texto)
        vistos: set[tuple[str, str]] = set()
        resultado: list[tuple[str, str]] = []
        for ent in doc.ents:
            superficie = ent.text.strip()
            tipo = _SPACY_MAP.get(ent.label_, "otro")
            if len(superficie) < _MIN_LARGO:
                continue
            clave = (superficie.lower(), tipo)
            if clave in vistos:
                continue
            vistos.add(clave)
            resultado.append((superficie, tipo))
        return resultado
