"""Parámetros de comportamiento del sistema (calibrables sin tocar la lógica)."""

from __future__ import annotations

from dataclasses import dataclass, field

# Modelos de Whisper ofrecidos en la GUI, del más rápido al más preciso.
# large-v3-turbo es el punto dulce para transcribir (calidad cercana a
# large-v3 a una fracción del tiempo); large-v3 solo compensa si el material
# es corto y se busca el techo de precisión. Para un texto que va a
# publicarse, `small` se queda corto en nombres propios y terminología.
MODELOS_WHISPER: list[str] = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3-turbo",
    "large-v3",
]

# Horas de proceso por hora de audio en CPU int8 (órdenes de magnitud, no
# medidas de esta máquina): solo sirven para el ETA de la PRIMERA vez.
# TimeEstimator.calibrar() los reemplaza con el desempeño real medido.
FACTOR_TIEMPO_POR_MODELO: dict[str, float] = {
    "tiny": 0.10,
    "base": 0.15,
    "small": 0.50,
    "medium": 1.30,
    "large-v3-turbo": 0.80,
    "large-v3": 2.50,
}

# Sobrecosto de tiempo de la diarización sobre el de transcribir: hay que
# decodificar el audio y sacar un embedding por segmento, mucho más barato
# que Whisper pero no gratis.
FACTOR_TIEMPO_DIARIZACION = 0.15


@dataclass
class TranscriptionSettings:
    modelo: str = "small"  # ver MODELOS_WHISPER
    idioma: str = "es"
    compute_type: str = "int8"  # CPU sin GPU: int8 es lo más rápido
    # Whisper en CPU satura los cores: un solo worker para transcribir.
    max_workers: int = 1
    # Factor inicial: horas de proceso por hora de video con `small` en CPU.
    # Se recalibra con el tiempo real medido tras el primer video.
    factor_tiempo_inicial: float = 0.5
    # Defaults = los mismos de faster-whisper: actualizar el proyecto no
    # cambia el comportamiento de nadie que no los ajuste explícitamente.
    beam_size: int = 5  # bajar a 1-2 gana velocidad, pierde algo de precisión
    initial_prompt: str = ""  # vocabulario/contexto técnico opcional
    # False evita "loops" de alucinación en grabaciones largas, a costa de
    # perder coherencia de contexto entre segmentos.
    condition_on_previous_text: bool = True


@dataclass
class DiarizationSettings:
    """Quién habla y cuándo. 100 % local ($0): embeddings de voz ECAPA +
    agrupamiento; no usa API ni modelos con licencia restringida."""

    activa: bool = True
    # 0 = deducir cuántas voces hay. Si sabes el número (una entrevista son
    # 2), fijarlo es MUCHO más fiable que cualquier umbral automático.
    n_hablantes: int = 0
    # Distancia coseno bajo la cual dos tramos se consideran la misma voz.
    # Solo se usa en modo automático (n_hablantes = 0).
    #
    # De dónde sale 0.65: speechbrain considera "mismo hablante" una
    # similitud coseno >= 0.25 (threshold por defecto de verify_batch), o
    # sea distancia <= 0.75; se baja a 0.65 porque el enlace promedio del
    # agrupamiento compara grupos, no pares sueltos, y tiende a fundir.
    #
    # SIN CALIBRAR CON GRABACIONES REALES: es un punto de partida tomado de
    # la convención de la librería, no una medición sobre este material.
    # Subirlo funde voces distintas; bajarlo inventa hablantes de más. Si
    # sabes cuántas personas hablan, fijar n_hablantes evita este umbral.
    umbral_distancia: float = 0.65
    # Tramos más cortos que esto no dan un embedding de voz confiable: se
    # dejan sin etiqueta y heredan el hablante del tramo anterior.
    duracion_minima_s: float = 0.6
    modelo: str = "speechbrain/spkrec-ecapa-voxceleb"


@dataclass
class SegmentationSettings:
    pausa_frontera_s: float = 2.0  # gap entre segmentos que marca frontera dura
    umbral_coseno: float = 0.55  # similitud entre ventanas bajo la cual se corta
    ventana_segmentos: int = 4  # tamaño de las ventanas comparadas
    chunk_min_s: float = 30.0
    chunk_max_s: float = 300.0
    # Un cambio de hablante corta el chunk. Desactivarlo da chunks más
    # largos (mejor contexto para el RAG) a costa de mezclar voces en un
    # mismo fragmento, que es lo que arruina la atribución de una cita.
    cortar_por_hablante: bool = True


@dataclass
class SearchSettings:
    # Pesos vinculantes de la spec (04_AI_Architecture Parte 3).
    peso_semantico: float = 0.45
    peso_textual: float = 0.30
    peso_entidades: float = 0.15
    peso_confianza: float = 0.10
    candidatos_por_fuente: int = 50
    usar_rrf: bool = False  # RRF de referencia para tests comparativos
    rrf_k: int = 60


# Catálogo de modelos por proveedor: la app recomienda el primero (default),
# pero el combo de la GUI es editable — el usuario puede escribir cualquier
# otro modelo vigente sin esperar una recompilación.
MODELOS_POR_PROVEEDOR: dict[str, list[str]] = {
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "openai": ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-4.1-mini"],
    "claude": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    "ollama": ["llama3.1", "qwen2.5", "mistral"],
    # lmstudio no tiene catálogo fijo: se llena en la GUI consultando
    # /v1/models del servidor local (lo que el usuario tenga cargado ahí).
    "lmstudio": [],
}


def modelo_recomendado(proveedor: str) -> str:
    modelos = MODELOS_POR_PROVEEDOR.get(proveedor, [])
    return modelos[0] if modelos else ""


@dataclass
class RAGSettings:
    proveedor: str = "gemini"
    modelo: str = "gemini-2.5-flash"
    k_evidencias: int = 8
    umbral_evidencia: float = 0.25  # bajo esto no se llama al LLM


@dataclass
class Settings:
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    diarization: DiarizationSettings = field(default_factory=DiarizationSettings)
    segmentation: SegmentationSettings = field(default_factory=SegmentationSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)


SETTINGS = Settings()


def factor_tiempo(modelo: str, con_diarizacion: bool) -> float:
    """Factor de ETA inicial para un modelo de Whisper concreto (+ el
    sobrecosto de diarizar, si está activa)."""
    base = FACTOR_TIEMPO_POR_MODELO.get(modelo, SETTINGS.transcription.factor_tiempo_inicial)
    return base + (FACTOR_TIEMPO_DIARIZACION if con_diarizacion else 0.0)


def _archivo_preferencias():
    from videoindex.config import paths

    return paths.DATA_DIR / "preferencias.json"


def _leer_preferencias() -> dict:
    import json

    ruta = _archivo_preferencias()
    if not ruta.exists():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir_preferencias(nuevas: dict) -> None:
    """Mezcla sobre lo ya guardado en vez de reemplazar el archivo: las
    preferencias de RAG y las de transcripción se guardan desde pestañas
    distintas del mismo diálogo y una no puede borrar a la otra."""
    import json

    from videoindex.config import paths

    paths.ensure_dirs()
    datos = _leer_preferencias()
    datos.update(nuevas)
    _archivo_preferencias().write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cargar_preferencias_rag() -> None:
    """Restaura proveedor/modelo elegidos en una sesión anterior (no es
    secreto, así que va en un JSON simple, no en el keyring)."""
    datos = _leer_preferencias()
    if datos.get("proveedor"):
        SETTINGS.rag.proveedor = datos["proveedor"]
    if datos.get("modelo"):
        SETTINGS.rag.modelo = datos["modelo"]


def guardar_preferencias_rag(proveedor: str, modelo: str) -> None:
    SETTINGS.rag.proveedor = proveedor
    SETTINGS.rag.modelo = modelo
    _escribir_preferencias({"proveedor": proveedor, "modelo": modelo})


def cargar_preferencias_transcripcion() -> None:
    """Modelo de Whisper y ajustes de diarización elegidos antes."""
    datos = _leer_preferencias()
    if datos.get("whisper_modelo"):
        SETTINGS.transcription.modelo = datos["whisper_modelo"]
    if datos.get("whisper_idioma"):
        SETTINGS.transcription.idioma = datos["whisper_idioma"]
    if "diarizacion_activa" in datos:
        SETTINGS.diarization.activa = bool(datos["diarizacion_activa"])
    if "diarizacion_n_hablantes" in datos:
        SETTINGS.diarization.n_hablantes = int(datos["diarizacion_n_hablantes"])
    if "diarizacion_umbral" in datos:
        SETTINGS.diarization.umbral_distancia = float(datos["diarizacion_umbral"])


def guardar_preferencias_transcripcion(
    modelo: str, idioma: str, diarizacion_activa: bool, n_hablantes: int, umbral: float
) -> None:
    SETTINGS.transcription.modelo = modelo
    SETTINGS.transcription.idioma = idioma
    SETTINGS.diarization.activa = diarizacion_activa
    SETTINGS.diarization.n_hablantes = n_hablantes
    SETTINGS.diarization.umbral_distancia = umbral
    _escribir_preferencias(
        {
            "whisper_modelo": modelo,
            "whisper_idioma": idioma,
            "diarizacion_activa": diarizacion_activa,
            "diarizacion_n_hablantes": n_hablantes,
            "diarizacion_umbral": umbral,
        }
    )
