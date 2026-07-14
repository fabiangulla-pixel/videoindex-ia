"""Exportación del corpus como bundle OKF (Open Knowledge Format, Google
Cloud, jun-2026): un directorio de archivos markdown con frontmatter YAML,
enlazados entre sí, para que cualquier agente de IA los lea sin depender de
esta app ni de su búsqueda híbrida (FAISS/FTS5/entidades).

No sustituye a SearchEngine/RAGService — es una capa de PORTABILIDAD: el
mismo conocimiento que ya extrae el pipeline (chunks, entidades,
anotaciones) reempacado para consumo externo. Sin llamadas a LLM: es
repaquetado local, mismo espíritu $0 que export_service.py (del que también
toma el patrón "un video / un proyecto").

Spec de referencia: github.com/GoogleCloudPlatform/knowledge-catalog/
blob/main/okf/SPEC.md — cada concepto es un archivo con frontmatter
(type/title/description/resource/tags/timestamp) + cuerpo markdown
estructurado; las relaciones entre conceptos son links markdown relativos,
sin tipar (la prosa alrededor explica la relación). OKF deja embeddings e
indexación fuera de su alcance a propósito: por eso este módulo no toca
SearchEngine, solo re-describe lo que ya hay en SQLite.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from videoindex.application.rag_service import _fmt_tiempo
from videoindex.domain.models import Annotation, Entity, SemanticChunk, Video
from videoindex.infrastructure.db.repositories import (
    AnnotationRepo,
    ChunkRepo,
    EntityRepo,
    ProjectRepo,
    VideoRepo,
)


def _slug(texto: str, unico: str) -> str:
    """Slug legible; el sufijo del id evita colisiones aunque dos videos o
    entidades compartan título/label (los links entre archivos dependen de
    que el slug sea único, a diferencia del nombre de archivo suelto que ya
    usaba exportar_proyecto_json)."""
    base = "".join(c if c.isalnum() else "-" for c in texto.strip().lower())
    while "--" in base:
        base = base.replace("--", "-")
    base = base.strip("-") or "sin-titulo"
    return f"{base}-{unico[:8]}"


def _yaml_valor(v: str) -> str:
    escapado = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escapado}"'


def _frontmatter(campos: dict[str, str | list[str] | None]) -> str:
    lineas = ["---"]
    for clave, valor in campos.items():
        if not valor:
            continue
        if isinstance(valor, list):
            lineas.append(f"{clave}:")
            lineas.extend(f"  - {_yaml_valor(v)}" for v in valor)
        else:
            lineas.append(f"{clave}: {_yaml_valor(valor)}")
    lineas.append("---")
    return "\n".join(lineas)


def _resource_uri(path: str) -> str | None:
    """URI file:// del archivo; si el path no es absoluto (dato corrupto o
    importado de otra máquina) cae de vuelta al string crudo en vez de
    reventar la exportación completa por un solo video."""
    try:
        return Path(path).as_uri()
    except ValueError:
        return path


@dataclass
class _Aparicion:
    video_id: str
    video_slug: str
    video_title: str
    start_time: float


@dataclass
class _EntidadAcumulada:
    entity: Entity
    apariciones: list[_Aparicion] = field(default_factory=list)


class _ConstructorBundle:
    """Acumula los archivos de un bundle (uno o varios videos) antes de
    escribirlos a disco, para fusionar entidades repetidas entre videos de
    un mismo proyecto en un solo archivo en vez de duplicarlo."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self._nombres_proyecto = {p.project_id: p.name for p in ProjectRepo(con).listar()}
        self._chunk_repo = ChunkRepo(con)
        self._entity_repo = EntityRepo(con)
        self._annotation_repo = AnnotationRepo(con)
        self.videos: list[tuple[str, str]] = []  # (slug, title), orden de inserción
        self._videos_md: dict[str, str] = {}  # slug -> contenido
        self._entidades: dict[str, _EntidadAcumulada] = {}  # entity_id -> acumulado

    def agregar_video(self, video: Video) -> None:
        slug = _slug(video.title, video.video_id)
        self.videos.append((slug, video.title))

        entidades, chunks_por_entidad = self._entity_repo.catalogo_de_video(video.video_id)
        chunks = {c.chunk_id: c for c in self._chunk_repo.por_video(video.video_id)}

        entidades_por_chunk: dict[str, list[tuple[str, str]]] = {}
        for eid, cids in chunks_por_entidad.items():
            for cid in cids:
                entidades_por_chunk.setdefault(cid, []).append((eid, entidades[eid].label))

        for eid, ent in entidades.items():
            acumulado = self._entidades.setdefault(eid, _EntidadAcumulada(entity=ent))
            for cid in chunks_por_entidad.get(eid, []):
                chunk = chunks.get(cid)
                if chunk is None:
                    continue
                acumulado.apariciones.append(
                    _Aparicion(video.video_id, slug, video.title, chunk.start_time)
                )

        anotaciones = self._annotation_repo.por_video(video.video_id)
        self._videos_md[slug] = self._render_video(
            video, slug, chunks, entidades_por_chunk, anotaciones
        )

    def _render_video(
        self,
        video: Video,
        slug: str,
        chunks: dict[str, SemanticChunk],
        entidades_por_chunk: dict[str, list[tuple[str, str]]],
        anotaciones: list[Annotation],
    ) -> str:
        tags = []
        nombre_proyecto = self._nombres_proyecto.get(video.project_id)
        if nombre_proyecto:
            tags.append(nombre_proyecto)
        if video.course_name:
            tags.append(video.course_name)

        frontmatter = _frontmatter(
            {
                "type": "Video",
                "title": video.title,
                "description": (
                    f"{_fmt_tiempo(video.duration_seconds or 0)} — {len(chunks)} fragmento(s)"
                ),
                "resource": _resource_uri(video.path) if video.path else None,
                "tags": tags,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        lineas = [frontmatter, "", f"# {video.title}", ""]
        if tags:
            lineas.append(f"**Proyecto/curso:** {', '.join(tags)}  ")
        lineas.append(f"**Estado:** {video.processing_status}  ")
        lineas += [
            "",
            "## Fragmentos",
            "",
            "| Inicio | Fin | Texto | Entidades |",
            "|---|---|---|---|",
        ]
        for c in sorted(chunks.values(), key=lambda c: c.start_time):
            pares = entidades_por_chunk.get(c.chunk_id, [])
            ents_txt = (
                ", ".join(f"[{lbl}](../entities/{_slug(lbl, eid)}.md)" for eid, lbl in pares) or "—"
            )
            texto = c.full_text.replace("|", "\\|").replace("\n", " ")
            lineas.append(
                f"| {_fmt_tiempo(c.start_time)} | {_fmt_tiempo(c.end_time)} | {texto} | {ents_txt} |"
            )
        if anotaciones:
            lineas += ["", "## Anotaciones manuales", ""]
            lineas += [f"- {_fmt_tiempo(a.timestamp_s)} — {a.text}" for a in anotaciones]
        return "\n".join(lineas) + "\n"

    def _render_entidades(self) -> dict[str, str]:
        archivos = {}
        for eid, acumulado in self._entidades.items():
            ent = acumulado.entity
            apariciones = sorted(acumulado.apariciones, key=lambda a: (a.video_title, a.start_time))
            n_videos = len({a.video_id for a in apariciones})
            frontmatter = _frontmatter(
                {
                    "type": "Entity",
                    "title": ent.label,
                    "description": f"{ent.entity_type} — mencionada en {n_videos} video(s)",
                    "tags": [ent.entity_type],
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            lineas = [
                frontmatter,
                "",
                f"# {ent.label}",
                "",
                f"**Tipo:** {ent.entity_type}",
                "",
                "## Apariciones",
                "",
            ]
            lineas += [
                f"- [{a.video_title}](../videos/{a.video_slug}.md) — {_fmt_tiempo(a.start_time)}"
                for a in apariciones
            ]
            archivos[_slug(ent.label, eid)] = "\n".join(lineas) + "\n"
        return archivos

    def _render_index(self, titulo_bundle: str) -> str:
        frontmatter = _frontmatter(
            {
                "type": "Bundle",
                "title": titulo_bundle,
                "description": f"{len(self.videos)} video(s), {len(self._entidades)} entidad(es)",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        lineas = [frontmatter, "", f"# {titulo_bundle}", "", "## Videos", ""]
        lineas += [f"- [{titulo}](videos/{slug}.md)" for slug, titulo in self.videos]
        lineas += ["", "## Entidades", ""]
        lineas += [
            f"- [{acumulado.entity.label}](entities/{_slug(acumulado.entity.label, eid)}.md)"
            for eid, acumulado in self._entidades.items()
        ]
        return "\n".join(lineas) + "\n"

    def escribir(self, carpeta: Path, titulo_bundle: str) -> list[Path]:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "videos").mkdir(exist_ok=True)
        (carpeta / "entities").mkdir(exist_ok=True)

        escritos = []
        for slug, contenido in self._videos_md.items():
            ruta = carpeta / "videos" / f"{slug}.md"
            ruta.write_text(contenido, encoding="utf-8")
            escritos.append(ruta)
        for slug, contenido in self._render_entidades().items():
            ruta = carpeta / "entities" / f"{slug}.md"
            ruta.write_text(contenido, encoding="utf-8")
            escritos.append(ruta)

        ruta_index = carpeta / "index.md"
        ruta_index.write_text(self._render_index(titulo_bundle), encoding="utf-8")
        escritos.append(ruta_index)
        return escritos


def exportar_video_okf(con: sqlite3.Connection, video_id: str, carpeta: str | Path) -> list[Path]:
    """Bundle OKF de UN video: index.md + videos/<slug>.md + entities/<slug>.md
    por cada entidad detectada en él. Lanza ValueError si no existe."""
    video = VideoRepo(con).por_id(video_id)
    if video is None:
        raise ValueError(f"Video no encontrado: {video_id}")
    constructor = _ConstructorBundle(con)
    constructor.agregar_video(video)
    return constructor.escribir(Path(carpeta), video.title)


def exportar_proyecto_okf(
    con: sqlite3.Connection, project_id: str | None, carpeta: str | Path
) -> list[Path]:
    """Bundle OKF de un proyecto completo (mismo sentinel que VideoRepo.listar:
    "__todos__" es toda la biblioteca, None son los videos sin proyecto). Las
    entidades que aparecen en más de un video del proyecto quedan en UN solo
    archivo, con una aparición por cada video que las menciona. Los videos no
    completados se omiten (aún no tienen corpus que exportar)."""
    constructor = _ConstructorBundle(con)
    for video in VideoRepo(con).listar(project_id):
        if video.processing_status != "completed":
            continue
        constructor.agregar_video(video)

    if project_id not in ("__todos__", None):
        nombres_proyecto = {p.project_id: p.name for p in ProjectRepo(con).listar()}
        titulo = nombres_proyecto.get(project_id, "Proyecto")
    else:
        titulo = "Biblioteca completa" if project_id == "__todos__" else "Sin proyecto"
    return constructor.escribir(Path(carpeta), titulo)
