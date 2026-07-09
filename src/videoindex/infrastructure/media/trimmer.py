"""Recorte de video SIN re-codificar: remux de paquetes con PyAV.

Copiar los paquetes comprimidos tal cual (stream copy) hace que recortar una
grabación de 2 h tome segundos incluso en una máquina sin GPU — re-codificar
tomaría horas en esta CPU. El precio: el corte de inicio cae en el keyframe
anterior más cercano (en grabaciones de Zoom suele haber uno cada pocos
segundos), así que la precisión es de ±unos segundos, suficiente para quitar
esperas iniciales y colas.

El archivo ORIGINAL nunca se modifica: el recorte se escribe en un archivo
nuevo. La identidad de un video en la biblioteca es su checksum (SAD §3.4),
así que el recortado es un video NUEVO a todos los efectos y sus timestamps
de transcripción serán absolutos sobre el archivo recortado (ADR-002).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

# Margen (s) tras el fin pedido para dejar de demuxear: los paquetes de audio
# y video llegan intercalados con desfase pequeño; sin margen se perdería la
# cola de audio del último tramo.
_MARGEN_CORTE_S = 5.0


def recortar_video(
    origen: str | Path,
    destino: str | Path,
    inicio_s: float,
    fin_s: float | None = None,
    progreso: Callable[[float], None] | None = None,
) -> Path:
    """Escribe en `destino` el tramo [inicio_s, fin_s] de `origen` copiando
    paquetes (sin re-codificar). fin_s None = hasta el final del archivo.
    progreso(fraccion 0..1) se emite por cada paquete de video.

    Lanza ValueError si el rango es inválido; cualquier fallo de PyAV se
    propaga (el llamador decide cómo mostrarlo)."""
    import av

    origen, destino = Path(origen), Path(destino)
    if inicio_s < 0:
        raise ValueError(f"inicio_s no puede ser negativo: {inicio_s}")
    if fin_s is not None and fin_s <= inicio_s:
        raise ValueError(f"fin_s ({fin_s}) debe ser mayor que inicio_s ({inicio_s})")

    with av.open(str(origen)) as entrada, av.open(str(destino), "w") as salida:
        streams_entrada = [s for s in entrada.streams if s.type in ("video", "audio")]
        if not streams_entrada:
            raise ValueError(f"El archivo no tiene streams de video/audio: {origen}")
        mapa = {s.index: salida.add_stream_from_template(s) for s in streams_entrada}

        duracion_total = (entrada.duration or 0) / av.time_base
        fin_efectivo = fin_s if fin_s is not None else duracion_total
        ventana = max(fin_efectivo - inicio_s, 0.001)

        if inicio_s > 0:
            # seek global: retrocede al keyframe anterior a inicio_s (por eso
            # el corte real puede empezar unos segundos antes de lo pedido).
            entrada.seek(int(inicio_s * av.time_base))

        # Primer dts visto por stream: se resta para que el archivo recortado
        # arranque en t=0 (sin esto, el reproductor mostraría el tramo con
        # los timestamps originales y una "espera" fantasma al inicio).
        offsets: dict[int, int] = {}
        for packet in entrada.demux(streams_entrada):
            if packet.dts is None:
                continue
            t = float(packet.dts * packet.time_base)
            if fin_s is not None and t > fin_s:
                if t > fin_s + _MARGEN_CORTE_S:
                    break
                continue

            indice = packet.stream.index
            if indice not in offsets:
                offsets[indice] = packet.dts
            offset = offsets[indice]
            packet.dts -= offset
            if packet.pts is not None:
                packet.pts -= offset

            destino_stream = mapa[indice]
            packet.stream = destino_stream
            salida.mux(packet)

            if progreso and destino_stream.type == "video":
                progreso(min(1.0, max(0.0, (t - inicio_s) / ventana)))

    return destino
