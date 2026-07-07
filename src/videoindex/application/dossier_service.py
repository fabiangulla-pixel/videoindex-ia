"""Dossier del video: cobertura COMPLETA del contenido por entidad, no un
top-k de búsqueda como el RAG puntual (RAGService.preguntar()).

Reutiliza el contrato exacto de rag_service.py — evidencia obligatoria, gate
sin evidencia, citas [n], confirmación de costo antes / costo real después
(ADR-003) — aplicado N veces (una por entidad) sobre una única instancia de
LLMProvider, para que su usages() acumule correctamente y el costo real se
calcule con una sola llamada agregada al final.

No depende de SearchEngine/embeddings/FAISS: el dossier recopila TODO lo
del video, no busca por relevancia.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from videoindex.application.rag_service import (
    SYSTEM_PROMPT,
    _fmt_tiempo,
    construir_prompt_usuario,
    parsear_citas,
)
from videoindex.config.settings import RAGSettings
from videoindex.domain.models import DossierEntidad, Entity, Evidence, RAGAnswer
from videoindex.domain.ports import LLMProvider
from videoindex.infrastructure.db.repositories import ChunkRepo, EntityRepo
from videoindex.infrastructure.llm import costos
from videoindex.infrastructure.llm.costos import CostoReal, EstimacionCosto


@dataclass
class EstimacionDossier:
    """Agregado de N EstimacionCosto (una por entidad con evidencia). No vive
    en costos.py para no alterar su contrato de "una sola llamada"."""

    estimaciones: list[tuple[Entity, EstimacionCosto]]
    proveedor: str
    modelo: str

    @property
    def costo_total_usd(self) -> float:
        return sum(e.costo_usd for _, e in self.estimaciones)

    @property
    def es_local(self) -> bool:
        return self.proveedor in costos.PROVEEDORES_LOCALES

    def resumen(self) -> str:
        if self.es_local:
            return f"Modelo local ({self.modelo} vía {self.proveedor}): costo $0."
        n = len(self.estimaciones)
        return (
            f"Modelo: {self.modelo} ({self.proveedor})\n"
            f"Entidades a cubrir: {n}\n\n"
            f"COSTO TOTAL ESTIMADO: ${self.costo_total_usd:,.4f} USD\n\n"
            "(Suma de una llamada al LLM por entidad; estimación aproximada, "
            f"ver {costos.PRECIOS_VERIFICADOS_EL}.)"
        )


class DossierService:
    def __init__(self, con: sqlite3.Connection, cfg: RAGSettings | None = None):
        self.entity_repo = EntityRepo(con)
        self.chunk_repo = ChunkRepo(con)
        self.cfg = cfg or RAGSettings()

    def recopilar_evidencia_por_entidad(
        self, video_id: str, video_title: str
    ) -> list[tuple[Entity, list[Evidence]]]:
        """TODAS las entidades del video con TODOS sus chunks como Evidence,
        en orden cronológico (ya vienen ordenados por catalogo_de_video)."""
        entidades, chunks_por_entidad = self.entity_repo.catalogo_de_video(video_id)
        chunks = {c.chunk_id: c for c in self.chunk_repo.por_video(video_id)}

        resultado: list[tuple[Entity, list[Evidence]]] = []
        for entity_id, entity in entidades.items():
            evidencias = []
            for chunk_id in chunks_por_entidad.get(entity_id, []):
                chunk = chunks.get(chunk_id)
                if chunk is None:
                    continue
                evidencias.append(
                    Evidence(
                        chunk_id=chunk.chunk_id,
                        video_id=video_id,
                        video_title=video_title,
                        start_time=chunk.start_time,
                        end_time=chunk.end_time,
                        text=chunk.full_text,
                    )
                )
            resultado.append((entity, evidencias))
        return resultado

    def estimar_dossier(
        self,
        entidades_evidencia: list[tuple[Entity, list[Evidence]]],
        proveedor: str,
        modelo: str,
    ) -> EstimacionDossier:
        estimaciones = [
            (
                entity,
                costos.estimar_pregunta_rag(
                    entity.label, [e.text for e in evidencias], SYSTEM_PROMPT, proveedor, modelo
                ),
            )
            for entity, evidencias in entidades_evidencia
            if evidencias
        ]
        return EstimacionDossier(estimaciones=estimaciones, proveedor=proveedor, modelo=modelo)

    def generar(
        self,
        entidades_evidencia: list[tuple[Entity, list[Evidence]]],
        llm: LLMProvider,
        proveedor: str,
    ) -> tuple[list[DossierEntidad], CostoReal]:
        """Llama al LLM al menos una vez por entidad con evidencia — nunca
        por entidades sin evidencia (gate, ADR-003). El costo real se calcula
        UNA sola vez al final, agregado sobre las N llamadas acumuladas en
        llm.usages() — no se prorratea por entidad (sería precisión falsa)."""
        resultados: list[DossierEntidad] = []
        for entity, evidencias in entidades_evidencia:
            if not evidencias:
                continue
            texto = llm.ask(SYSTEM_PROMPT, construir_prompt_usuario(entity.label, evidencias))
            citas = parsear_citas(texto, len(evidencias))
            answer = RAGAnswer(text=texto, evidences=evidencias, cited_indices=citas)
            resultados.append(
                DossierEntidad(
                    entity_id=entity.entity_id,
                    entity_label=entity.label,
                    entity_type=entity.entity_type,
                    answer=answer,
                    chunks_cubiertos=len(evidencias),
                )
            )
        real = costos.costo_real_desde_usages(proveedor, llm.model_name, llm.usages())
        return resultados, real

    @staticmethod
    def exportar_markdown(video_title: str, dossier: list[DossierEntidad]) -> str:
        """Devuelve el Markdown como string — sin I/O de archivo (el caller
        escribe a disco), para que sea testeable de forma pura. No depende
        de self (sin acceso a BD): se puede llamar sin instanciar el servicio."""
        lineas = [f"# Dossier: {video_title}", ""]
        for d in dossier:
            lineas += [f"## {d.entity_label} ({d.entity_type})", "", d.answer.text, ""]
            lineas.append("**Fuentes citadas:**")
            for i, e in enumerate(d.answer.evidences, 1):
                marca = "" if i in d.answer.cited_indices else " (no citada)"
                lineas.append(f"- [{i}] {e.video_title} — {_fmt_tiempo(e.start_time)}{marca}")
            lineas.append("")
        return "\n".join(lineas)
