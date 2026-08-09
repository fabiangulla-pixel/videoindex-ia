"""Adaptación supervisada del espacio de voces a ESTE material.

ECAPA viene entrenado con VoxCeleb: inglés, audio de YouTube, miles de
hablantes. Este documental es otra cosa — español de Chile y México, música
de fondo, voz en off de estudio mezclada con entrevistas en exteriores. El
modelo separa bien, pero no *para este material*: el narrador salió partido
en dos voces.

En vez de reentrenar la red (haría falta GPU y un corpus etiquetado), se
aprende una **proyección lineal discriminante (LDA)** sobre sus embeddings.
Es la técnica estándar de los sistemas de diarización sobre x-vectors: el
modelo grande extrae la representación y una capa pequeña, entrenada con
datos del dominio, la reordena para que las voces de ESTE material queden
lo más separadas posible.

Las etiquetas no se anotan a mano: salen de los rótulos del video. Cuando
aparece "CARLA ULLOA" en pantalla, los tramos de habla de esa ventana son
suyos. Es supervisión débil, pero es supervisión real y gratis.

Se mide antes y después con el mismo criterio que importa editorialmente:
1. ¿Se funden dos personas distintas? (error grave: cita falsa)
2. ¿Se parte una misma persona en varias voces? (error leve: se arregla a mano)
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

TRABAJO = pathlib.Path(r"D:\Chile\workeo\transcripcion_work")
DESTINO = pathlib.Path(r"C:\Users\Lenovo\VideoIndexIA\data\modelos\voces_lda.npz")
MARGEN = 6.0


def log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def cargar():
    from videoindex.application.rotulos_service import Rotulo
    from videoindex.infrastructure.diarization.ecapa_provider import EcapaDiarizationProvider
    from videoindex.infrastructure.media.audio import cargar_audio_mono

    segs = json.loads((TRABAJO / "segmentos.json").read_text(encoding="utf-8"))
    rots = [Rotulo(**r) for r in json.loads((TRABAJO / "rotulos.json").read_text(encoding="utf-8"))]
    regiones = [(s["start"], s["end"]) for s in segs]

    prov = EcapaDiarizationProvider()
    audio = cargar_audio_mono(str(next(TRABAJO.glob("*.m4a"))))
    idx, ondas = prov._recortar_regiones(audio, regiones)
    log(f"Extrayendo embeddings de {len(idx)} tramos de habla…")
    V = prov._embeddings(ondas, None)
    return regiones, [regiones[i] for i in idx], V, rots


def etiquetas_debiles(regiones_utiles, rotulos):
    """Etiqueta cada tramo con la persona rotulada en ese momento, si la hay."""
    from videoindex.application.identificacion_service import (
        canonizar_nombres,
        interpretar_rotulo,
    )
    from videoindex.domain.diarization import solapamiento

    inter = [(r, i) for r in rotulos if (i := interpretar_rotulo(r)) is not None]
    canon = canonizar_nombres([n for _, (n, _, _) in inter])
    etiquetas: list[str | None] = []
    for inicio, fin in regiones_utiles:
        quien = None
        for r, (nombre, _, _) in inter:
            if solapamiento(inicio, fin, r.inicio_s - MARGEN, r.fin_s + MARGEN) > 0:
                quien = canon[nombre]
                break
        etiquetas.append(quien)
    return etiquetas


def evaluar(V, regiones_utiles, etiquetas, umbral, titulo):
    """Cuenta los dos errores que importan, con el mismo criterio que la app."""
    from sklearn.cluster import AgglomerativeClustering

    grupos = AgglomerativeClustering(
        n_clusters=None, distance_threshold=umbral, metric="cosine", linkage="average"
    ).fit_predict(V)

    por_persona: dict[str, set[int]] = {}
    por_grupo: dict[int, set[str]] = {}
    for g, quien in zip(grupos, etiquetas, strict=True):
        if quien is None:
            continue
        por_persona.setdefault(quien, set()).add(int(g))
        por_grupo.setdefault(int(g), set()).add(quien)

    fusion = sum(len(v) - 1 for v in por_grupo.values() if len(v) > 1)
    fragmentacion = sum(len(v) - 1 for v in por_persona.values() if len(v) > 1)
    log(
        f"  {titulo:22} voces={len(set(grupos)):3}  fusión={fusion:2}  "
        f"fragmentación={fragmentacion:2}"
    )
    return len(set(grupos)), fusion, fragmentacion


def main() -> int:
    regiones, utiles, V, rots = cargar()
    etiq = etiquetas_debiles(utiles, rots)
    conocidas = [(v, e) for v, e in zip(V, etiq, strict=True) if e is not None]
    personas = sorted({e for _, e in conocidas})
    log(f"{len(conocidas)}/{len(V)} tramos con etiqueta de rótulo, {len(personas)} personas")
    if len(personas) < 3:
        log("Muy pocas personas etiquetadas para aprender una proyección.")
        return 1

    # PARTICIÓN HONESTA. Ajustar la proyección y medirla con las MISMAS
    # etiquetas garantiza un resultado bonito y falso: LDA separa por
    # construcción los puntos que vio. Se aparta la mitad de las apariciones
    # de cada persona (las más tardías) y solo ahí se mide.
    from collections import defaultdict

    indices_por_persona = defaultdict(list)
    for i, (region, quien) in enumerate(zip(utiles, etiq, strict=True)):
        if quien is not None:
            indices_por_persona[quien].append((region[0], i))

    entrenar_idx, probar_idx = [], []
    for apariciones in indices_por_persona.values():
        apariciones.sort()
        corte = len(apariciones) // 2
        if corte == 0:  # con una sola aparición no se puede partir
            entrenar_idx += [i for _, i in apariciones]
            continue
        entrenar_idx += [i for _, i in apariciones[:corte]]
        probar_idx += [i for _, i in apariciones[corte:]]
    log(f"{len(entrenar_idx)} tramos para ajustar, {len(probar_idx)} apartados para medir")
    if len(probar_idx) < 15:
        log("Muy pocos tramos apartados para una medición creíble.")
        return 1

    etiq_prueba = [etiq[i] if i in set(probar_idx) else None for i in range(len(utiles))]

    log("ANTES (ECAPA tal cual), medido SOLO en los tramos apartados:")
    base = evaluar(V, utiles, etiq_prueba, 0.75, "ECAPA original")

    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

    X = np.array([V[i] for i in entrenar_idx])
    y = np.array([etiq[i] for i in entrenar_idx])
    clases = sorted(set(y))
    lda = LinearDiscriminantAnalysis(n_components=min(len(clases) - 1, X.shape[1]))
    lda.fit(X, y)
    log(f"Proyección aprendida con {len(X)} tramos: 192 -> {lda.scalings_.shape[1]} dims")

    def proyectar(M):
        P = lda.transform(M)
        return P / np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-10)

    Vp = proyectar(V)
    log("DESPUÉS (proyectado), medido en los MISMOS tramos apartados:")
    mejor = None
    for u in (0.05, 0.10, 0.20, 0.35, 0.50, 0.70):
        n_voces, fusion, frag = evaluar(Vp, utiles, etiq_prueba, u, f"LDA umbral {u:.2f}")
        # Un número de voces disparatado descalifica el umbral por muy bien
        # que salgan los errores: 161 voces en un documental no es un
        # resultado, es ruido.
        if n_voces > 3 * len(personas):
            continue
        clave = (fusion, frag, n_voces)
        if mejor is None or clave < mejor[0]:
            mejor = (clave, u, (n_voces, fusion, frag))

    if mejor is None:
        log("Ningún umbral da un número de voces plausible: la proyección no sirve.")
        return 0
    _, u_mejor, r_mejor = mejor
    log(
        f"Mejor umbral {u_mejor:.2f}   voces {base[0]}->{r_mejor[0]}   "
        f"fusión {base[1]}->{r_mejor[1]}   fragmentación {base[2]}->{r_mejor[2]}"
    )

    if r_mejor[1] > base[1] or (r_mejor[1] == base[1] and r_mejor[2] >= base[2]):
        log("La proyección NO mejora sobre datos no vistos: no se guarda nada.")
        return 0

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        DESTINO,
        scalings=lda.scalings_,
        xbar=lda.xbar_ if hasattr(lda, "xbar_") else np.zeros(V.shape[1]),
        umbral=u_mejor,
        personas=np.array(personas),
    )
    log(f"Proyección guardada en {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
