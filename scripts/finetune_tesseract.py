"""Fine-tuning de Tesseract para la tipografía de los rótulos del video.

**De dónde salen las etiquetas.** No hay corpus anotado a mano: se usa el
consenso temporal como maestro. Un rótulo se lee 4-9 veces mientras está en
pantalla; el consenso acierta (>0.90) donde el fotograma suelto falla
("%LEDAD BIANCHI", "IANCHI"). Entrenar el reconocimiento de un fotograma
hacia el texto del consenso es **destilación**: el alumno aprende de una
señal más limpia que la suya propia.

Riesgo asumido y acotado: si el consenso se equivocara, el modelo aprendería
el error. Por eso solo se usan rótulos con confianza >= 0.88 y al menos 3
lecturas coincidentes, y al final se MIDE contra un conjunto de validación
apartado antes de entrenar.

Flujo (herramientas oficiales de Tesseract, ya instaladas):
  fotogramas -> recortes .tif + .gt.txt -> .lstmf -> lstmtraining --continue_from
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TESS = Path(r"C:\Program Files\Tesseract-OCR")
VIDEO = Path(r"D:\Chile\workeo\Estravagario - documental completo.mp4")
ROTULOS = Path(r"D:\Chile\workeo\transcripcion_work\rotulos.json")
TRABAJO = Path(r"D:\Chile\workeo\finetune_tesseract")
TESSDATA_BASE = Path(r"C:\Users\Lenovo\VideoIndexIA\data\modelos\tessdata")
# Para CONTINUAR el entrenamiento hace falta el modelo FLOAT de tessdata_best.
# El de `tessdata` a secas es entero ("fast", cuantizado) y lstmtraining lo
# rechaza: "is an integer (fast) model, cannot continue training".
TESSDATA_ENTRENABLE = Path(r"C:\Users\Lenovo\VideoIndexIA\data\modelos\tessdata_best")

CONFIANZA_MINIMA = 0.88
APARICIONES_MINIMAS = 3
PROPORCION_VALIDACION = 0.25
ITERACIONES = 400


def log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def ejecutar(cmd: list[str], tessdata: Path | None = None, **kw) -> subprocess.CompletedProcess:
    """Los binarios de Tesseract necesitan el entorno COMPLETO (DLLs del
    sistema en el PATH); pasarles solo dos variables los deja sin cargar.

    `tessdata` elige QUÉ modelo ve el binario, y no es un detalle: los
    .lstmf de entrenamiento tienen que generarse con el MISMO modelo con el
    que se va a entrenar. Generarlos con el `fast` y entrenar con el `best`
    produce "Deserialize header failed" en unas cuantas muestras y aborta
    todo el entrenamiento, porque sus unicharsets no coinciden.
    """
    import os

    entorno = dict(os.environ)
    entorno["TESSDATA_PREFIX"] = str(tessdata or TESSDATA_BASE)
    entorno["PATH"] = f"{TESS};{entorno.get('PATH', '')}"
    kw.setdefault("env", entorno)
    # encoding + errors explícitos: la salida de Tesseract trae bytes que la
    # consola cp1252 de Windows no sabe decodificar, y sin esto el propio
    # subprocess.run lanza UnicodeDecodeError. Pasó de verdad: la validación
    # de muestras daba "77/77 válidas" porque nunca llegaba a leer los
    # mensajes de error.
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw
    )


def _escribir_box(base: Path, texto: str, ancho: int, alto: int) -> None:
    """Archivo .box en formato WordStr, que es lo que espera lstm.train.

    La imagen es UNA línea de texto, así que la caja abarca la imagen entera
    y el contenido va como una sola cadena. La segunda fila marca el fin de
    línea (convención de las herramientas de entrenamiento de Tesseract).
    """
    base.with_suffix(".box").write_text(
        f"WordStr 0 0 {ancho} {alto} 0 #{texto}\n{ancho + 1} 0 {ancho + 2} {alto} 0\n",
        encoding="utf-8",
    )


def generar_muestras() -> list[tuple[Path, str]]:
    """Un recorte por LÍNEA de rótulo, no la franja entera.

    El LSTM de Tesseract se entrena con imágenes de una sola línea: darle la
    franja completa (1920x432, dos líneas y fondo) no le enseña nada. Las
    cajas de cada línea las da el propio OCR; el TEXTO de referencia lo da el
    consenso temporal, que es más fiable que la lectura de ese fotograma.

    Se toman varios instantes de cada rótulo: el fondo cambia por detrás del
    texto y esa variación es justo lo que debe aprender a ignorar.
    """
    import numpy as np
    import pytesseract
    from PIL import Image

    from videoindex.application.rotulos_service import normalizar
    from videoindex.infrastructure.media.frames import extraer_fotogramas, recortar_franja
    from videoindex.infrastructure.ocr.tesseract_ocr import _preparar

    idioma = _preparar()
    TRABAJO.mkdir(parents=True, exist_ok=True)
    rotulos = json.loads(ROTULOS.read_text(encoding="utf-8"))
    utiles = [
        r
        for r in rotulos
        if r["confianza"] >= CONFIANZA_MINIMA
        and r["apariciones"] >= APARICIONES_MINIMAS
        and all(len(linea) <= 45 for linea in r["lineas"])
    ]
    log(f"{len(utiles)}/{len(rotulos)} rótulos superan el filtro de calidad")

    muestras: list[tuple[Path, str]] = []
    for i, r in enumerate(utiles):
        instantes = [
            r["inicio_s"] + d for d in (0.5, 1.5, 2.5) if r["inicio_s"] + d <= r["fin_s"]
        ] or [r["inicio_s"]]
        for j, t in enumerate(instantes):
            fotograma = next(extraer_fotogramas(VIDEO, 1.0, t, t + 1.2), None)
            if fotograma is None:
                continue
            franja = recortar_franja(fotograma.imagen, 0.60, 1.0)
            datos = pytesseract.image_to_data(
                Image.fromarray(franja),
                lang=idioma,
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )
            # Cajas de cada línea detectada en este fotograma.
            cajas: dict[tuple[int, int], list] = {}
            for texto, conf, bl, ln, x, y, w, h in zip(
                datos["text"],
                datos["conf"],
                datos["block_num"],
                datos["line_num"],
                datos["left"],
                datos["top"],
                datos["width"],
                datos["height"],
                strict=True,
            ):
                if texto.strip() and float(conf) >= 60:
                    cajas.setdefault((bl, ln), []).append((texto.strip(), x, y, w, h))
            for palabras in cajas.values():
                leido = " ".join(p for p, *_ in palabras)
                # Se empareja con la línea del consenso que más se le parece:
                # el fotograma pudo leerla mal, y el texto bueno es el del
                # consenso, no el de este cuadro.
                objetivo = max(
                    r["lineas"],
                    key=lambda linea: len(
                        set(normalizar(linea).split()) & set(normalizar(leido).split())
                    ),
                    default=None,
                )
                if objetivo is None:
                    continue
                comunes = set(normalizar(objetivo).split()) & set(normalizar(leido).split())
                if not comunes:
                    continue  # no es la misma línea: no se puede etiquetar
                x0 = max(0, min(x for _, x, *_ in palabras) - 8)
                y0 = max(0, min(y for _, _, y, *_ in palabras) - 6)
                x1 = min(franja.shape[1], max(x + w for _, x, _, w, _ in palabras) + 8)
                y1 = min(franja.shape[0], max(y + h for _, _, y, _, h in palabras) + 6)
                if x1 - x0 < 40 or y1 - y0 < 12:
                    continue
                recorte = np.ascontiguousarray(franja[y0:y1, x0:x1])
                base = TRABAJO / f"linea_{i:03d}_{j}_{len(muestras):04d}"
                imagen = Image.fromarray(recorte).convert("L")
                imagen.save(base.with_suffix(".tif"))
                base.with_suffix(".gt.txt").write_text(objetivo, encoding="utf-8")
                _escribir_box(base, objetivo, imagen.width, imagen.height)
                muestras.append((base, objetivo))
    log(f"{len(muestras)} líneas recortadas (imagen + caja + texto de referencia)")
    return muestras


def a_lstmf(muestras: list[tuple[Path, str]]) -> list[Path]:
    """Convierte cada par imagen/texto al formato de entrenamiento."""
    hechos = []
    for base, _ in muestras:
        r = ejecutar(
            [
                str(TESS / "tesseract.exe"),
                str(base.with_suffix(".tif")),
                str(base),
                "--psm",
                "6",
                "-l",
                "spa",
                "lstm.train",
            ],
            tessdata=TESSDATA_ENTRENABLE,
        )
        salida = base.with_suffix(".lstmf")
        if salida.exists():
            hechos.append(salida)
        elif len(hechos) == 0:
            log(f"  aviso al convertir {base.name}: {(r.stderr or '')[:200]}")
    log(f"{len(hechos)} archivos .lstmf generados")

    return hechos


def descartar_ilegibles(lstmf: list[Path]) -> list[Path]:
    """Quita las muestras que el entrenador no consigue deserializar.

    Un puñado de .lstmf sale corrupto — se genera sin error y `lstmeval`
    individual tampoco protesta, pero `lstmtraining` los rechaza con
    "Deserialize header failed" y **aborta el entrenamiento entero**. No
    hay forma barata de predecirlos por tamaño ni por contenido, así que se
    le pregunta al propio entrenador: se lanza una pasada de cero
    iteraciones, se leen los nombres que denuncia y se apartan.
    """
    lista = TRABAJO / "sonda.txt"
    descartados: set[str] = set()
    for intento in range(4):
        quedan = [p for p in lstmf if str(p) not in descartados]
        lista.write_text("\n".join(str(p) for p in quedan), encoding="utf-8")
        sonda = ejecutar(
            [
                str(TESS / "lstmtraining.exe"),
                "--model_output",
                str(TRABAJO / "sonda"),
                "--continue_from",
                str(TRABAJO / "spa.lstm"),
                "--traineddata",
                str(TESSDATA_ENTRENABLE / "spa.traineddata"),
                "--train_listfile",
                str(lista),
                "--max_iterations",
                "1",
            ],
            tessdata=TESSDATA_ENTRENABLE,
        )
        texto = (sonda.stderr or "") + (sonda.stdout or "")
        malos = re.findall(r"Deserialize header failed: (.+\.lstmf)", texto)
        if not malos:
            log(f"  sonda {intento + 1}: ninguna muestra ilegible más")
            break
        descartados.update(m.strip() for m in malos)
        log(f"  sonda {intento + 1}: {len(malos)} muestras ilegibles apartadas")
    lista.unlink(missing_ok=True)
    validos = [p for p in lstmf if str(p) not in descartados]
    log(f"{len(validos)}/{len(lstmf)} muestras utilizables")
    return validos


def main() -> int:
    muestras = generar_muestras()
    if len(muestras) < 20:
        log("Muy pocas muestras para entrenar; se aborta.")
        return 1

    # Se extrae la red LSTM del modelo español antes de nada: hace falta
    # tanto para validar cada muestra como para continuar el entrenamiento.
    base_lstm = TRABAJO / "spa.lstm"
    ejecutar(
        [
            str(TESS / "combine_tessdata.exe"),
            "-e",
            str(TESSDATA_ENTRENABLE / "spa.traineddata"),
            str(base_lstm),
        ]
    )
    if not base_lstm.exists():
        log("No se pudo extraer spa.lstm del modelo base; se aborta.")
        return 1

    lstmf = descartar_ilegibles(a_lstmf(muestras))
    if len(lstmf) < 20:
        log("No se pudieron generar suficientes .lstmf; se aborta.")
        return 1

    random.seed(7)
    random.shuffle(lstmf)
    corte = int(len(lstmf) * (1 - PROPORCION_VALIDACION))
    entrenamiento, validacion = lstmf[:corte], lstmf[corte:]
    (TRABAJO / "train.txt").write_text("\n".join(str(p) for p in entrenamiento), encoding="utf-8")
    (TRABAJO / "eval.txt").write_text("\n".join(str(p) for p in validacion), encoding="utf-8")
    log(f"{len(entrenamiento)} para entrenar, {len(validacion)} apartadas para validar")

    log("Midiendo el modelo BASE sobre las muestras apartadas…")
    antes = ejecutar(
        [
            str(TESS / "lstmeval.exe"),
            "--model",
            str(base_lstm),
            "--traineddata",
            str(TESSDATA_ENTRENABLE / "spa.traineddata"),
            "--eval_listfile",
            str(TRABAJO / "eval.txt"),
        ]
    )
    log((antes.stderr or antes.stdout).strip().splitlines()[-1][:200])

    log(f"Entrenando {ITERACIONES} iteraciones (fine-tuning desde el modelo español)…")
    entrenar = ejecutar(
        [
            str(TESS / "lstmtraining.exe"),
            "--model_output",
            str(TRABAJO / "rotulos"),
            "--continue_from",
            str(base_lstm),
            "--traineddata",
            str(TESSDATA_ENTRENABLE / "spa.traineddata"),
            "--train_listfile",
            str(TRABAJO / "train.txt"),
            "--eval_listfile",
            str(TRABAJO / "eval.txt"),
            "--max_iterations",
            str(ITERACIONES),
            "--target_error_rate",
            "0.01",
        ]
    )
    salida = (entrenar.stderr or "") + (entrenar.stdout or "")
    for linea in salida.splitlines()[-12:]:
        log("  " + linea[:160])

    checkpoint = TRABAJO / "rotulos_checkpoint"
    if not checkpoint.exists():
        log("El entrenamiento no dejó checkpoint; ver salida arriba.")
        return 1

    log("Empaquetando el modelo afinado…")
    ejecutar(
        [
            str(TESS / "lstmtraining.exe"),
            "--stop_training",
            "--continue_from",
            str(checkpoint),
            "--traineddata",
            str(TESSDATA_ENTRENABLE / "spa.traineddata"),
            "--model_output",
            str(TESSDATA_BASE / "rotulos.traineddata"),
        ]
    )
    final = TESSDATA_BASE / "rotulos.traineddata"
    log(f"Modelo afinado: {final} ({'existe' if final.exists() else 'NO se creó'})")

    if final.exists():
        log("Midiendo el modelo AFINADO sobre las MISMAS muestras apartadas…")
        despues = ejecutar(
            [
                str(TESS / "lstmeval.exe"),
                "--model",
                str(TRABAJO / "rotulos_checkpoint"),
                "--traineddata",
                str(TESSDATA_ENTRENABLE / "spa.traineddata"),
                "--eval_listfile",
                str(TRABAJO / "eval.txt"),
            ]
        )
        log((despues.stderr or despues.stdout).strip().splitlines()[-1][:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
