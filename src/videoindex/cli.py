"""CLI de VideoIndex IA — permite el flujo E2E antes de que exista la GUI.

Uso:
    python -m videoindex.cli ingest "C:\\ruta\\videos" [--curso NOMBRE] [--si]
    python -m videoindex.cli search "concepto a buscar" [-k 10]
    python -m videoindex.cli status
"""

from __future__ import annotations

import argparse
import logging
import sys

from videoindex.config import paths
from videoindex.config.settings import SETTINGS


def _servicios():
    """Construcción tardía: los modelos pesados solo se cargan al usarse."""
    from videoindex.application.search_engine import SearchEngine
    from videoindex.infrastructure.db.connection import conectar
    from videoindex.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider
    from videoindex.infrastructure.ner.spacy_ner_provider import SpacyNERProvider
    from videoindex.infrastructure.vector.faiss_index import FaissIndex

    paths.ensure_dirs()
    con = conectar(paths.DB_PATH)
    embedder = LocalEmbeddingProvider()
    ner = SpacyNERProvider()
    faiss_index = FaissIndex(paths.FAISS_DIR / "v1.faiss", embedder.dimensions)
    buscador = SearchEngine(con, embedder, ner, faiss_index, SETTINGS.search)
    return con, embedder, ner, faiss_index, buscador


def _fmt_tiempo(segundos: float) -> str:
    m, s = divmod(int(segundos), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def cmd_ingest(args: argparse.Namespace) -> int:
    from videoindex.application.ingest_service import IngestService
    from videoindex.application.pipeline_service import PipelineService
    from videoindex.application.time_estimator import TimeEstimator
    from videoindex.infrastructure.transcription.faster_whisper_provider import (
        FasterWhisperProvider,
    )

    con, embedder, ner, faiss_index, _ = _servicios()
    ingesta = IngestService(con)
    resultado = ingesta.escanear_carpeta(args.carpeta, args.curso)

    print(
        f"Nuevos: {len(resultado.nuevos)} | pendientes previos: {len(resultado.pendientes_previos)}"
        f" | ya completados: {len(resultado.ya_completados)}"
    )
    por_procesar = resultado.por_procesar
    if not por_procesar:
        print("Nada que procesar.")
        return 0

    estimador = TimeEstimator(SETTINGS.transcription.factor_tiempo_inicial)
    duraciones = [v.duration_seconds or 0.0 for v in por_procesar]
    eta = estimador.eta_lote(duraciones)
    print(
        f"\nPor procesar: {len(por_procesar)} videos ({sum(duraciones) / 3600:.1f} h de material)"
    )
    print("Costo API: $0 (transcripción y embeddings 100% locales)")
    print(
        f"Tiempo estimado: ~{TimeEstimator.humano(eta)} (whisper {SETTINGS.transcription.modelo}, CPU)"
    )

    if not args.si:
        respuesta = input("¿Continuar? [s/N] ").strip().lower()
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado. Los videos quedaron registrados como pendientes.")
            return 0

    transcriptor = FasterWhisperProvider(
        SETTINGS.transcription.modelo,
        SETTINGS.transcription.idioma,
        SETTINGS.transcription.compute_type,
    )
    pipeline = PipelineService(con, transcriptor, embedder, ner, faiss_index, SETTINGS)

    def progreso(video_id: str, etapa: str, fraccion: float) -> None:
        print(f"  [{fraccion * 100:5.1f}%] {etapa}")

    ok, fail = pipeline.procesar_lote(por_procesar, progreso, estimador.calibrar)
    print(f"\nCompletados: {ok} | fallidos: {fail}")
    return 0 if fail == 0 else 1


def cmd_search(args: argparse.Namespace) -> int:
    _, _, _, _, buscador = _servicios()
    resultados = buscador.search(args.query, args.k)
    if not resultados:
        print("Sin resultados.")
        return 0
    for i, r in enumerate(resultados, 1):
        b = r.breakdown
        print(
            f"\n[{i}] {r.video_title}  {_fmt_tiempo(r.start_time)}–{_fmt_tiempo(r.end_time)}"
            f"  score={r.score:.3f}"
        )
        print(
            f"    (sem={b.semantico:.2f} txt={b.textual:.2f} ent={b.entidades:.2f} conf={b.confianza:.2f})"
        )
        print(f"    {r.snippet}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    from videoindex.infrastructure.db.connection import conectar

    paths.ensure_dirs()
    con = conectar(paths.DB_PATH)
    filas = con.execute(
        "SELECT processing_status, COUNT(*) AS n FROM videos GROUP BY processing_status"
    ).fetchall()
    total_chunks = con.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0]
    total_ents = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    print(f"BD: {paths.DB_PATH}")
    for f in filas:
        print(f"  {f['processing_status']}: {f['n']}")
    print(f"  chunks: {total_chunks} | entidades: {total_ents}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="videoindex", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ingest = sub.add_parser("ingest", help="registrar y procesar una carpeta de videos")
    p_ingest.add_argument("carpeta")
    p_ingest.add_argument("--curso", default=None)
    p_ingest.add_argument("--si", action="store_true", help="no pedir confirmación")
    p_ingest.set_defaults(func=cmd_ingest)

    p_search = sub.add_parser("search", help="búsqueda híbrida")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_status = sub.add_parser("status", help="estado de la biblioteca")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
