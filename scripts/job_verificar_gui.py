"""Prueba de punta a punta del flujo REAL de la GUI sobre el documental.

No llama a los servicios por debajo: instancia los mismos QThread que dispara
la interfaz (PipelineWorker, IdentificarHablantesWorker,
PaqueteEditorialWorker) y espera sus señales. Es la diferencia entre "los
servicios funcionan" y "la app funciona": por el camino están el hilo propio,
la conexión SQLite por hilo, el caché de modelos y el guardado en BD, que los
tests con datos falsos no ejercitan.

Para no volver a pagar los 65 min de CPU de la transcripción, se precargan
en la BD los segmentos ya calculados y se deja que el pipeline REANUDE desde
ahí — lo que de paso prueba la reanudación con material real.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

VIDEO = Path(r"D:\Chile\workeo\Estravagario - documental completo.mp4")
TRABAJO = Path(r"D:\Chile\workeo\transcripcion_work")
SALIDA = Path(r"D:\Chile\workeo\resultado_desde_la_app")
URL = "https://www.youtube.com/watch?v=1tq_BbCzp80"

fallos: list[str] = []


def log(mensaje: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {mensaje}", flush=True)


def comprobar(condicion: bool, descripcion: str) -> None:
    log(f"  {'[OK]  ' if condicion else '[FALLO]'} {descripcion}")
    if not condicion:
        fallos.append(descripcion)


def esperar(worker, senales: list[str], timeout_s: float = 7200):
    """Arranca el worker y bloquea hasta su primera señal terminal."""
    from PySide6.QtCore import QCoreApplication

    recibido = {}

    def guardar(nombre):
        def _(*args):
            recibido["nombre"] = nombre
            recibido["args"] = args

        return _

    for nombre in [*senales, "fallo"]:
        getattr(worker, nombre).connect(guardar(nombre))
    worker.start()
    limite = time.time() + timeout_s
    while not recibido and time.time() < limite:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    worker.wait(5000)
    return recibido


def preparar_biblioteca() -> str:
    """Da de alta el documental y precarga la transcripción ya calculada."""
    from videoindex.application.ingest_service import IngestService
    from videoindex.config import paths
    from videoindex.domain.models import TranscriptSegment
    from videoindex.infrastructure.db.connection import conectar
    from videoindex.infrastructure.db.repositories import SegmentRepo, VideoRepo
    from videoindex.infrastructure.media.youtube import MediaDescargado

    con = conectar(paths.DB_PATH)
    try:
        media = MediaDescargado(
            ruta=VIDEO,
            titulo="Estravagario: la literatura chilena en México",
            url=URL,
            canal="YouTube",
        )
        resultado = IngestService(con).registrar_descarga(media)
        video = (resultado.nuevos + resultado.pendientes_previos + resultado.ya_completados)[0]
        log(f"En biblioteca: {video.title} ({video.video_id[:8]})")

        repo = SegmentRepo(con)
        if not repo.por_video(video.video_id):
            datos = json.loads((TRABAJO / "segmentos.json").read_text(encoding="utf-8"))
            repo.guardar_lote(
                [
                    TranscriptSegment(
                        segment_id=str(uuid4()),
                        video_id=video.video_id,
                        start_time=s["start"],
                        end_time=s["end"],
                        raw_text=s["raw"],
                        clean_text=s["texto"],
                        confidence=s["confianza"],
                    )
                    for s in datos
                ]
            )
            VideoRepo(con).actualizar_estado(video.video_id, "transcribing")
            log(f"Precargados {len(datos)} segmentos; el pipeline debe REANUDAR desde el final")
        return video.video_id, video.path
    finally:
        con.close()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from videoindex.config import paths
    from videoindex.config.settings import cargar_preferencias_transcripcion
    from videoindex.infrastructure.db.connection import conectar
    from videoindex.infrastructure.db.repositories import SegmentRepo, SpeakerRepo, VideoRepo
    from videoindex.presentation.workers import (
        IdentificarHablantesWorker,
        PaqueteEditorialWorker,
        PipelineWorker,
    )

    QApplication(sys.argv)
    cargar_preferencias_transcripcion()
    video_id, ruta = preparar_biblioteca()

    log("=== 1/3 PipelineWorker (reanuda, diariza, indexa) ===")
    w = PipelineWorker([video_id])
    w.progreso.connect(
        lambda vid, etapa, f: (
            log(f"    {etapa} {f * 100:.0f}%") if etapa != "transcribing" else None
        )
    )
    r = esperar(w, ["terminado"])
    comprobar(r.get("nombre") == "terminado", f"el pipeline termina sin fallo ({r})")
    if r.get("nombre") == "terminado":
        comprobar(r["args"] == (1, 0), f"1 completado, 0 fallidos (vio {r['args']})")

    con = conectar(paths.DB_PATH)
    try:
        estado = VideoRepo(con).por_id(video_id).processing_status
        segs = SegmentRepo(con).por_video(video_id)
    finally:
        con.close()
    comprobar(estado == "completed", f"estado final 'completed' (vio '{estado}')")
    comprobar(len(segs) > 500, f"la transcripción precargada sobrevivió ({len(segs)} segmentos)")
    con_voz = sum(1 for s in segs if s.speaker)
    comprobar(con_voz > 400, f"la diarización etiquetó los segmentos ({con_voz}/{len(segs)})")

    log("=== 2/3 IdentificarHablantesWorker (OCR de rótulos, tarda) ===")
    w2 = IdentificarHablantesWorker(video_id, ruta)
    w2.progreso.connect(lambda f, m: log(f"    {m}") if int(f * 100) % 20 == 0 else None)
    r2 = esperar(w2, ["listo"])
    comprobar(r2.get("nombre") == "listo", f"la identificación termina sin fallo ({r2})")
    identidades, rotulos = (r2.get("args") or ([], []))[:2]
    comprobar(len(rotulos) > 20, f"lee los rótulos del video ({len(rotulos)})")
    con_nombre = [i for i in identidades if i.nombre]
    comprobar(len(con_nombre) >= 6, f"propone nombre para varias voces ({len(con_nombre)})")
    for ident in con_nombre:
        log(f"      {ident.descriptor}  [{ident.confianza}]")

    # Lo que haría el usuario al aceptar en el diálogo.
    con = conectar(paths.DB_PATH)
    try:
        repo = SpeakerRepo(con)
        for ident in con_nombre:
            repo.renombrar(video_id, ident.speaker_label, ident.nombre)
        guardados = repo.nombres(video_id)
    finally:
        con.close()
    comprobar(len(guardados) == len(con_nombre), "los nombres se guardan en la BD")

    log("=== 3/3 PaqueteEditorialWorker ===")
    w3 = PaqueteEditorialWorker(video_id, str(SALIDA), rotulos)
    r3 = esperar(w3, ["listo"])
    comprobar(r3.get("nombre") == "listo", f"el paquete se genera sin fallo ({r3})")
    salidas = (r3.get("args") or [{}])[0]
    comprobar(len(salidas) == 8, f"ocho documentos (vio {len(salidas)})")

    if salidas:
        from docx import Document

        doc = Document(str(salidas["limpia"]))
        texto = "\n".join(p.text for p in doc.paragraphs)
        comprobar("SPEAKER_" not in texto, "el Word no muestra etiquetas técnicas")
        comprobar(
            any(i.nombre and i.nombre.upper() in texto for i in con_nombre),
            "los nombres identificados aparecen en el Word",
        )
        comprobar("Gracias por ver el video" not in texto, "sin alucinaciones en el Word")

    log("")
    log("VERIFICACION GUI OK" if not fallos else f"VERIFICACION GUI FALLO: {'; '.join(fallos)}")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
