"""Estimación de tokens y costo ANTES de llamar a la IA externa.

Estándar transversal de los proyectos con API key (adaptado de ReactivosFlow
infra/ai/costos.py): (1) contabilizar volumen, (2) estimar tokens, (3) traducir
a USD y pedir confirmación. Tras ejecutar se registra el costo REAL leído del
`usage` del proveedor.

Diseño deliberado:
- SIN tiktoken: heurística por caracteres, suficiente para estimar gasto.
- Precios CATALOGADOS con fuente y fecha. Modelo fuera de tabla → se estima con
  el precio más caro conocido (cota superior, nunca subestimar) y se marca.

Precios (USD por 1M tokens), verificados el 2026-07-06:
OpenAI (developers.openai.com/api/docs/pricing):
- gpt-5.5 $5/$30 · gpt-5.4 $2.50/$15 · gpt-5.4-mini $0.75/$3 · gpt-4.1 $2/$8
Gemini (ai.google.dev/gemini-api/docs/pricing):
- gemini-2.5-pro $1.25/$10 (≤200k) · gemini-2.5-flash $0.30/$2.50
- gemini-2.0-flash $0.10/$0.40
Claude (skill claude-api, tabla oficial cacheada 2026-06):
- claude-opus-4-8 $5/$25 · claude-sonnet-5 $3/$15 · claude-haiku-4-5 $1/$5
Ollama: local, $0.
LM Studio: local, $0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRECIOS_VERIFICADOS_EL = "2026-07-06"

PROVEEDORES_LOCALES = {"ollama", "lmstudio"}


@dataclass(frozen=True)
class PrecioModelo:
    input_por_millon: float
    output_por_millon: float


PRECIOS: dict[str, PrecioModelo] = {
    # OpenAI
    "gpt-5.5": PrecioModelo(5.00, 30.00),
    "gpt-5.4": PrecioModelo(2.50, 15.00),
    "gpt-5.4-mini": PrecioModelo(0.75, 3.00),
    "gpt-4.1": PrecioModelo(2.00, 8.00),
    "gpt-4.1-mini": PrecioModelo(0.40, 1.60),
    # Google Gemini
    "gemini-2.5-pro": PrecioModelo(1.25, 10.00),
    "gemini-2.5-flash": PrecioModelo(0.30, 2.50),
    "gemini-2.0-flash": PrecioModelo(0.10, 0.40),
    # Anthropic Claude
    "claude-opus-4-8": PrecioModelo(5.00, 25.00),
    "claude-sonnet-5": PrecioModelo(3.00, 15.00),
    "claude-haiku-4-5": PrecioModelo(1.00, 5.00),
}

CARACTERES_POR_TOKEN = 4.0

# Cota de salida de una respuesta RAG (respuesta con citas, no ensayo).
TOKENS_SALIDA_RAG = 1500


def _precio_de(modelo: str) -> tuple[PrecioModelo, bool]:
    base = (modelo or "").split(":")[0].strip().lower()
    if base in PRECIOS:
        return PRECIOS[base], True
    mas_caro = max(PRECIOS.values(), key=lambda p: p.output_por_millon)
    return mas_caro, False


def estimar_tokens(texto: str) -> int:
    if not texto:
        return 0
    return int(len(texto) / CARACTERES_POR_TOKEN) + 1


def _costo(tokens_in: int, tokens_out: int, precio: PrecioModelo) -> float:
    return (
        tokens_in / 1_000_000 * precio.input_por_millon
        + tokens_out / 1_000_000 * precio.output_por_millon
    )


@dataclass
class EstimacionCosto:
    modelo: str
    proveedor: str
    tokens_input: int
    tokens_output: int
    costo_usd: float
    modelo_catalogado: bool
    notas: list[str] = field(default_factory=list)

    @property
    def tokens_totales(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def es_local(self) -> bool:
        return self.proveedor in PROVEEDORES_LOCALES

    def resumen(self) -> str:
        if self.es_local:
            return f"Modelo local ({self.modelo} vía {self.proveedor}): costo $0."
        lineas = [
            f"Modelo: {self.modelo} ({self.proveedor})",
            f"Tokens estimados de entrada:  {self.tokens_input:,}",
            f"Tokens estimados de salida:   {self.tokens_output:,} (cota superior)",
            "",
            f"COSTO ESTIMADO: ${self.costo_usd:,.4f} USD",
        ]
        if not self.modelo_catalogado:
            lineas += [
                "",
                "⚠ Modelo sin precio catalogado: estimado con el precio más "
                "alto conocido (cota superior). El costo real puede ser MENOR.",
            ]
        lineas += [nota for nota in self.notas]
        lineas += ["", f"(Precios verificados el {PRECIOS_VERIFICADOS_EL}. Estimación aproximada.)"]
        return "\n".join(lineas)


def estimar_pregunta_rag(
    query: str, textos_evidencia: list[str], system_prompt: str, proveedor: str, modelo: str
) -> EstimacionCosto:
    """Estima la ÚNICA llamada del RAG: system + pregunta + evidencias → respuesta."""
    precio, catalogado = _precio_de(modelo)
    tokens_in = (
        estimar_tokens(system_prompt)
        + estimar_tokens(query)
        + sum(estimar_tokens(t) for t in textos_evidencia)
    )
    tokens_out = TOKENS_SALIDA_RAG
    es_local = proveedor in PROVEEDORES_LOCALES
    return EstimacionCosto(
        modelo=modelo,
        proveedor=proveedor,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        costo_usd=0.0 if es_local else _costo(tokens_in, tokens_out, precio),
        modelo_catalogado=catalogado or es_local,
        notas=[f"Evidencias enviadas: {len(textos_evidencia)}"],
    )


@dataclass
class CostoReal:
    modelo: str
    tokens_input: int
    tokens_output: int
    costo_usd: float

    def resumen(self) -> str:
        return (
            f"Costo real: ${self.costo_usd:,.4f} USD "
            f"({self.tokens_input:,} in / {self.tokens_output:,} out)"
        )


def costo_real_desde_usages(proveedor: str, modelo: str, usages: list) -> CostoReal:
    """Suma usages heterogéneos: dicts u objetos SDK (OpenAI/Gemini/Claude)."""
    precio, _ = _precio_de(modelo)
    tokens_in = 0
    tokens_out = 0
    for u in usages:
        if not u:
            continue
        if isinstance(u, dict):
            tokens_in += int(
                u.get("prompt_tokens") or u.get("input_tokens") or u.get("prompt_token_count") or 0
            )
            tokens_out += int(
                u.get("completion_tokens")
                or u.get("output_tokens")
                or u.get("candidates_token_count")
                or 0
            )
        else:  # objeto SDK: prueba los nombres de cada proveedor
            tokens_in += int(
                getattr(u, "prompt_tokens", 0)
                or getattr(u, "input_tokens", 0)
                or getattr(u, "prompt_token_count", 0)
                or 0
            )
            tokens_out += int(
                getattr(u, "completion_tokens", 0)
                or getattr(u, "output_tokens", 0)
                or getattr(u, "candidates_token_count", 0)
                or 0
            )
    costo = 0.0 if proveedor in PROVEEDORES_LOCALES else _costo(tokens_in, tokens_out, precio)
    return CostoReal(
        modelo=modelo, tokens_input=tokens_in, tokens_output=tokens_out, costo_usd=costo
    )
