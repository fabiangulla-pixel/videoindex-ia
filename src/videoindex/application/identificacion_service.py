"""Ponerle nombre a cada voz cruzando lo que se oye con lo que se ve.

La diarización solo dice "esta voz es distinta de esa otra". Quién es cada
una no está en el audio: en un documental o una entrevista el nombre aparece
en un rótulo sobreimpreso, y a veces se dice en voz alta al presentar a
alguien. Este servicio cruza las tres fuentes:

  turnos de voz  ×  rótulos en pantalla  ×  menciones verbales

y propone un nombre por etiqueta de hablante, **con su nivel de confianza y
la evidencia que lo respalda**. Nunca inventa: si no hay evidencia, deja una
identificación funcional ("VOZ NO IDENTIFICADA") y lo registra como
incertidumbre para que lo resuelva una persona.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from videoindex.application.rotulos_service import Rotulo
from videoindex.domain.diarization import solapamiento
from videoindex.domain.models import SpeakerTurn

ALTO, MEDIO, BAJO = "ALTO", "MEDIO", "BAJO"

# Un rótulo identifica a quien habla en ese momento. Se mira también un poco
# antes y después: el rótulo suele entrar un instante después de que la
# persona empieza a hablar, y a veces se queda puesto al terminar la frase.
MARGEN_ROTULO_S = 6.0

# Palabras que delatan que una línea del rótulo es un CARGO y no un nombre.
_CARGOS = (
    "POETA",
    "ESCRITOR",
    "ESCRITORA",
    "HISTORIADOR",
    "HISTORIADORA",
    "NOVELISTA",
    "PERIODISTA",
    "ENSAYISTA",
    "INVESTIGADOR",
    "INVESTIGADORA",
    "PROFESOR",
    "PROFESORA",
    "DOCTOR",
    "DOCTORA",
    "CRITICO",
    "CRÍTICA",
    "TRADUCTOR",
    "TRADUCTORA",
    "EDITOR",
    "EDITORA",
    "ACADEMICO",
    "ACADÉMICA",
    "DIRECTOR",
    "DIRECTORA",
    "CINEASTA",
    "ANTROPOLOGA",
    "ANTROPÓLOGA",
    "FILOSOFO",
    "FILÓSOFO",
    "SOCIOLOGO",
    "SOCIÓLOGO",
    "ARTISTA",
)
# Instituciones frecuentes en este dominio; se separan del cargo para poder
# consignarlas en su columna del registro de participantes.
_INSTITUCIONES = ("UNAM", "UAM", "COLMEX", "UDP", "USACH", "PUC", "UBA", "UC")

# Palabras que nunca aparecen dentro de un nombre propio pero sí en una frase.
# NO se incluyen las partículas de apellido (DE, DEL, LA, LAS, Y), que sí
# forman parte de nombres reales: "Juan de Dios", "García de la Vega".
_FUNCIONALES = {
    "QUE",
    "HE",
    "HA",
    "HAS",
    "HAN",
    "ES",
    "SON",
    "ERA",
    "FUE",
    "SE",
    "ME",
    "TE",
    "NOS",
    "LE",
    "LES",
    "MI",
    "TU",
    "SU",
    "SUS",
    "EN",
    "CON",
    "POR",
    "PARA",
    "SIN",
    "SOBRE",
    "UN",
    "UNA",
    "UNOS",
    "UNAS",
    "AL",
    "LO",
    "NO",
    "SI",
    "YA",
    "MUY",
    "MAS",
    "MÁS",
    "PERO",
    "COMO",
    "CUANDO",
    "DONDE",
    "VIVIDO",
    "DIJO",
    "DICE",
    "HABLA",
}

_MENCIONES = (
    re.compile(
        r"\bmi nombre es\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+){0,3})"
    ),
    re.compile(
        r"\byo soy\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+){0,3})"
    ),
    re.compile(
        r"\b(?:estamos con|entrevistamos a|les presento a|nos acompaña)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+){0,3})"
    ),
)


@dataclass
class Identidad:
    speaker_label: str
    nombre: str | None = None
    funcion: str | None = None
    institucion: str | None = None
    confianza: str = BAJO
    evidencias: list[str] = field(default_factory=list)
    primera_aparicion: float = 0.0
    ultima_aparicion: float = 0.0
    segundos_hablados: float = 0.0
    es_voz_en_off: bool = False

    @property
    def etiqueta_editorial(self) -> str:
        """Cómo debe aparecer en la transcripción publicable."""
        if self.nombre:
            return self.nombre.upper()
        if self.es_voz_en_off:
            return "VOZ EN OFF"
        return "VOZ NO IDENTIFICADA"

    @property
    def descriptor(self) -> str:
        """Nombre + cargo, para la PRIMERA aparición."""
        partes = [self.etiqueta_editorial]
        cargo = ", ".join(x for x in (self.funcion, self.institucion) if x)
        if cargo:
            partes.append(cargo)
        elif self.es_voz_en_off:
            partes.append("NARRACIÓN")
        return " — ".join(partes)


def _parece_nombre(linea: str) -> bool:
    """Una línea de rótulo es el NOMBRE de alguien.

    Hay que descartar las tarjetas que no identifican a nadie, sobre todo las
    citas de libros, porque atribuirle a una voz el título de un poemario o
    el nombre del autor citado sería un error grave en el documento final.
    Caso real de este material: «Confiesó que he vivido / Pablo Neruda, 1974».

    Tres filtros, cada uno por una razón distinta:
    - vocabulario de cargo o institución → es la línea del cargo, no el nombre;
    - palabras funcionales (que, he, en…) → es una frase, no un nombre. Se
      dejan pasar las partículas de apellido (de, del, la, y);
    - un año de cuatro cifras → es el pie de una cita, no una persona.
    """
    palabras = set(re.sub(r"[^\wÁÉÍÓÚÑ ]", " ", linea.upper()).split())
    if palabras & set(_CARGOS) or palabras & set(_INSTITUCIONES):
        return False
    if palabras & _FUNCIONALES:
        return False
    if re.search(r"\b(1[89]\d{2}|20\d{2})\b", linea):
        return False
    # Un nombre son 1-4 palabras; una frase larga es otra cosa.
    return 1 <= len(linea.split()) <= 4


def _separar_cargo(linea: str) -> tuple[str, str | None]:
    """'POETA INVESTIGADORA UNAM' -> ('POETA INVESTIGADORA', 'UNAM')."""
    tokens = linea.split()
    institucion = None
    restantes = []
    for token in tokens:
        limpio = re.sub(r"[^\wÁÉÍÓÚÑ]", "", token.upper())
        if limpio in _INSTITUCIONES:
            institucion = limpio
        else:
            restantes.append(token)
    return " ".join(restantes).strip(" ,"), institucion


def interpretar_rotulo(rotulo: Rotulo) -> tuple[str, str | None, str | None] | None:
    """(nombre, cargo, institución) si el rótulo identifica a una persona.

    Devuelve None para los rótulos que NO son identificaciones: citas de
    libros, títulos, fechas. Confundirlos sería atribuirle a alguien el
    nombre de un poemario.
    """
    if not rotulo.lineas:
        return None
    nombre = None
    cargo = None
    institucion = None
    for linea in rotulo.lineas:
        if nombre is None and _parece_nombre(linea):
            nombre = linea.strip()
        else:
            texto, inst = _separar_cargo(linea)
            if inst:
                institucion = inst
            if texto and cargo is None:
                cargo = texto
    if nombre is None:
        return None
    # Un nombre sin cargo y sin nada más puede ser cualquier cosa (el título
    # de una sección). Se acepta igual, pero quien llame baja la confianza.
    return nombre, cargo, institucion


@dataclass
class CitaEnPantalla:
    """Tarjeta que anuncia un texto literario leído en voz alta.

    En este documental los pasajes recitados se anuncian con una tarjeta
    («Confieso que he vivido / Pablo Neruda, 1974»). Esa tarjeta es evidencia
    DENTRO del video, que es lo único con lo que se puede atribuir un texto:
    deducir el autor por el estilo sería inventar.
    """

    inicio_s: float
    fin_s: float
    titulo: str
    autor: str | None = None
    anio: str | None = None


def interpretar_cita(rotulo: Rotulo) -> CitaEnPantalla | None:
    """Lee una tarjeta de cita. None si el rótulo identifica a una persona.

    Se apoya en el año: el pie de una cita lo lleva casi siempre y el rótulo
    de un entrevistado nunca. Sin año, hace falta que una línea parezca un
    nombre de autor y la otra un título (una frase, no un cargo).
    """
    if not rotulo.lineas or interpretar_rotulo(rotulo) is not None:
        return None

    titulo = None
    autor = None
    anio = None
    for linea in rotulo.lineas:
        encontrado = re.search(r"\b(1[89]\d{2}|20\d{2})\b", linea)
        resto = re.sub(r"\b(1[89]\d{2}|20\d{2})\b", "", linea).strip(" ,;.-—")
        if encontrado:
            anio = encontrado.group(1)
            if resto and autor is None:
                autor = resto
        elif titulo is None:
            titulo = linea.strip()
        elif autor is None:
            autor = linea.strip()

    if titulo is None and autor is None:
        return None
    return CitaEnPantalla(
        inicio_s=rotulo.inicio_s,
        fin_s=rotulo.fin_s,
        titulo=titulo or "No identificado",
        autor=autor,
        anio=anio,
    )


def menciones_verbales(segmentos: list[dict]) -> list[tuple[float, str]]:
    """(instante, nombre) dicho en voz alta con una fórmula de presentación."""
    encontradas: list[tuple[float, str]] = []
    for seg in segmentos:
        texto = seg.get("texto", "")
        for patron in _MENCIONES:
            for coincidencia in patron.finditer(texto):
                encontradas.append((float(seg["start"]), coincidencia.group(1).strip()))
    return encontradas


def _hablante_dominante(
    turnos: list[SpeakerTurn], inicio: float, fin: float
) -> tuple[str | None, float]:
    """Quién habla durante una ventana, y cuántos segundos lo hace."""
    acumulado: dict[str, float] = {}
    for turno in turnos:
        solape = solapamiento(inicio, fin, turno.start_time, turno.end_time)
        if solape > 0:
            acumulado[turno.speaker] = acumulado.get(turno.speaker, 0.0) + solape
    if not acumulado:
        return None, 0.0
    mejor = max(acumulado.items(), key=lambda kv: kv[1])
    return mejor[0], mejor[1]


def identificar(
    turnos: list[SpeakerTurn],
    rotulos: list[Rotulo],
    segmentos: list[dict] | None = None,
) -> list[Identidad]:
    """Una Identidad por etiqueta de hablante, con evidencia y confianza.

    La confianza sale de cuánta evidencia independiente la respalda:
    - ALTO: un rótulo con nombre Y cargo aparece mientras esa voz habla, y
      ninguna otra voz reclama ese mismo nombre.
    - MEDIO: hay rótulo pero la atribución es dudosa (varios candidatos, o
      el rótulo cae en un tramo compartido), o el nombre solo se dijo en voz
      alta sin respaldo visual.
    - BAJO: sin evidencia; se deja identificación funcional.
    """
    identidades: dict[str, Identidad] = {}
    for turno in turnos:
        ident = identidades.setdefault(
            turno.speaker,
            Identidad(
                speaker_label=turno.speaker,
                primera_aparicion=turno.start_time,
                ultima_aparicion=turno.end_time,
            ),
        )
        ident.primera_aparicion = min(ident.primera_aparicion, turno.start_time)
        ident.ultima_aparicion = max(ident.ultima_aparicion, turno.end_time)
        ident.segundos_hablados += turno.duration

    # --- evidencia visual: los rótulos ---------------------------------
    reclamos: dict[str, set[str]] = {}  # nombre -> etiquetas que lo reclaman
    for rotulo in rotulos:
        interpretado = interpretar_rotulo(rotulo)
        if interpretado is None:
            continue
        nombre, cargo, institucion = interpretado
        etiqueta, segundos = _hablante_dominante(
            turnos, rotulo.inicio_s - MARGEN_ROTULO_S, rotulo.fin_s + MARGEN_ROTULO_S
        )
        if etiqueta is None:
            continue
        reclamos.setdefault(nombre, set()).add(etiqueta)
        ident = identidades[etiqueta]
        marca = _mmss(rotulo.inicio_s)
        if ident.nombre is None:
            ident.nombre = nombre
            ident.funcion = cargo
            ident.institucion = institucion
            ident.confianza = ALTO if cargo and segundos >= 2.0 else MEDIO
            ident.evidencias.append(
                f"Rótulo en pantalla [{marca}]: «{rotulo.texto}» "
                f"(leído {rotulo.apariciones} veces, OCR {rotulo.confianza:.0%})"
            )
        elif ident.nombre != nombre:
            # Dos rótulos distintos sobre la misma voz: o la diarización
            # fundió dos personas, o el rótulo cayó sobre quien no era.
            ident.confianza = MEDIO
            ident.evidencias.append(
                f"CONFLICTO: otro rótulo [{marca}] dice «{nombre}» sobre esta misma voz"
            )
        else:
            ident.evidencias.append(f"Rótulo repetido [{marca}] confirma el nombre")

    # Un mismo nombre sobre dos voces distintas: la diarización partió a una
    # persona en dos, o el rótulo se atribuyó mal. En ambos casos, no es ALTO.
    for nombre, etiquetas in reclamos.items():
        if len(etiquetas) > 1:
            for etiqueta in etiquetas:
                identidades[etiqueta].confianza = MEDIO
                identidades[etiqueta].evidencias.append(
                    f"«{nombre}» aparece atribuido a {len(etiquetas)} voces distintas "
                    f"({', '.join(sorted(etiquetas))}): revisar si la separación de "
                    "voces partió a la misma persona"
                )

    # --- evidencia verbal ----------------------------------------------
    for instante, nombre in menciones_verbales(segmentos or []):
        etiqueta, _ = _hablante_dominante(turnos, instante, instante + 8.0)
        if etiqueta is None:
            continue
        ident = identidades[etiqueta]
        nota = f"Mención verbal [{_mmss(instante)}]: se nombra a «{nombre}»"
        if ident.nombre is None:
            ident.nombre = nombre
            ident.confianza = MEDIO  # sin respaldo visual no pasa de MEDIO
            ident.evidencias.append(nota)
        else:
            ident.evidencias.append(nota + " (no altera la identificación visual)")

    # --- voz en off ------------------------------------------------------
    # Una voz que habla mucho y a la que NUNCA le pusieron rótulo es, casi
    # siempre, la narración: en un documental el narrador no se rotula.
    for ident in identidades.values():
        if ident.nombre is None and ident.segundos_hablados >= 60.0:
            ident.es_voz_en_off = True
            ident.evidencias.append(
                f"Habla {ident.segundos_hablados / 60:.0f} min repartidos por todo el "
                "video y nunca aparece rotulada: se trata como voz en off / narración"
            )

    return sorted(identidades.values(), key=lambda i: i.primera_aparicion)


def _mmss(segundos: float) -> str:
    h, resto = divmod(int(max(0.0, segundos)), 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
