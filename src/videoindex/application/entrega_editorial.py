"""Paquete de entrega de una transcripción profesional.

Produce el juego completo de documentos con los que se trabaja una
transcripción destinada a publicarse:

  transcripcion_literal.docx     lo que se dijo, tal cual
  transcripcion_limpia.docx      legible, sin alterar el contenido
  transcripcion_completa.txt     la limpia en texto plano
  subtitulos.srt                 para el video
  participantes_identificados.xlsx   quién es quién, con su evidencia
  citas_literarias.xlsx          los textos leídos en voz alta
  incertidumbres.md              lo que tiene que resolver una persona
  proceso_tecnico.md             cómo se produjo todo esto

Dos principios recorren el módulo:

1. **Nunca inventar.** Un nombre solo aparece si hay evidencia en el propio
   video (un rótulo, una presentación en voz alta). Si no la hay, se usa una
   identificación funcional y el caso se anota en `incertidumbres.md`.
2. **Separar lo automático de lo humano.** Los documentos dicen en su primera
   página que son transcripción de máquina sin cotejar, y `incertidumbres.md`
   concentra lo que hay que revisar en vez de repartirlo por el texto.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from videoindex.application.identificacion_service import CitaEnPantalla, Identidad
from videoindex.application.transcript_export_service import ADVERTENCIA, marca_tiempo
from videoindex.domain.diarization import Intervencion, agrupar_intervenciones
from videoindex.domain.limpieza import limpiar_para_lectura
from videoindex.domain.models import TranscriptSegment

# Confianza media de Whisper por debajo de la cual conviene que alguien
# escuche el pasaje. exp(avg_logprob): 0.6 ya es una zona de dudas.
CONFIANZA_DUDOSA = 0.60
# Solo se listan los pasajes dudosos más graves; una lista de doscientos
# avisos no la revisa nadie.
MAX_PASAJES_DUDOSOS = 25


@dataclass
class Contexto:
    """De dónde salió el material y con qué se procesó."""

    titulo: str
    archivo: str
    duracion_s: float
    url: str | None = None
    canal: str | None = None
    publicado: str | None = None
    modelo_transcripcion: str = ""
    modelo_diarizacion: str = ""
    modelo_ocr: str = ""
    notas: list[str] = field(default_factory=list)


def _nombre_de(intervencion: Intervencion, identidades: dict[str, Identidad]) -> Identidad | None:
    return identidades.get(intervencion.speaker) if intervencion.speaker else None


def _etiqueta(
    intervencion: Intervencion, identidades: dict[str, Identidad], ya_presentados: set[str]
) -> str:
    """Nombre + cargo la PRIMERA vez; solo el nombre después.

    Repetir el cargo en cada intervención satura la lectura; omitirlo desde
    el principio deja al lector sin saber quién es cada quien.
    """
    identidad = _nombre_de(intervencion, identidades)
    if identidad is None:
        return "VOZ NO IDENTIFICADA"
    if identidad.speaker_label in ya_presentados:
        return identidad.etiqueta_editorial
    ya_presentados.add(identidad.speaker_label)
    return identidad.descriptor


def _es_lectura(
    intervencion: Intervencion, citas: Sequence[CitaEnPantalla]
) -> CitaEnPantalla | None:
    """La cita cuya tarjeta aparece durante esta intervención, si la hay."""
    for cita in citas:
        if intervencion.start_time - 4.0 <= cita.inicio_s <= intervencion.end_time:
            return cita
    return None


def construir_intervenciones(segmentos: list[TranscriptSegment]) -> list[Intervencion]:
    """Intervenciones legibles: se parten también por silencios largos para
    que una narración continua no salga como un párrafo de veinte minutos."""
    return agrupar_intervenciones(segmentos, pausa_maxima_s=20.0)


# --------------------------------------------------------------------------
# Documentos
# --------------------------------------------------------------------------


def _nuevo_docx(contexto: Contexto, subtitulo: str, identidades: list[Identidad]):
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.add_heading(contexto.titulo, level=0)
    doc.add_paragraph(subtitulo, style="Subtitle")

    tabla = doc.add_table(rows=0, cols=2)
    tabla.style = "Light Grid Accent 1"
    ficha = {
        "Archivo": contexto.archivo,
        "Duración": marca_tiempo(contexto.duracion_s),
        "Fuente": contexto.url or "—",
        "Canal / autor": contexto.canal or "—",
        "Publicado": contexto.publicado or "—",
        "Transcripción": contexto.modelo_transcripcion,
        "Separación de voces": contexto.modelo_diarizacion,
        "Generado": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
    }
    for clave, valor in ficha.items():
        celdas = tabla.add_row().cells
        celdas[0].text = clave
        celdas[1].text = str(valor)

    doc.add_paragraph()
    doc.add_paragraph(ADVERTENCIA, style="Intense Quote")

    doc.add_heading("Participantes", level=1)
    tabla_p = doc.add_table(rows=1, cols=4)
    tabla_p.style = "Light Grid Accent 1"
    for celda, titulo in zip(
        tabla_p.rows[0].cells, ("Identificación", "Función", "Confianza", "Aparece"), strict=True
    ):
        celda.text = titulo
        celda.paragraphs[0].runs[0].bold = True
    for identidad in identidades:
        celdas = tabla_p.add_row().cells
        celdas[0].text = identidad.etiqueta_editorial
        celdas[1].text = ", ".join(x for x in (identidad.funcion, identidad.institucion) if x) or (
            "NARRACIÓN" if identidad.es_voz_en_off else "—"
        )
        celdas[2].text = identidad.confianza
        celdas[3].text = marca_tiempo(identidad.primera_aparicion)

    doc.add_page_break()
    estilo = doc.styles["Normal"]
    estilo.font.size = Pt(11)
    return doc


def _escribir_cuerpo(doc, intervenciones, identidades, citas, limpiar: bool) -> None:
    from docx.shared import Pt, RGBColor

    doc.add_heading("Transcripción", level=1)
    ya_presentados: set[str] = set()
    cita_abierta: CitaEnPantalla | None = None

    for intervencion in intervenciones:
        cita = _es_lectura(intervencion, citas)
        if cita is not None and cita is not cita_abierta:
            cita_abierta = cita
            aviso = doc.add_paragraph()
            marca = aviso.add_run(
                f"[{marca_tiempo(intervencion.start_time)}] INICIO — LECTURA DE TEXTO"
            )
            marca.bold = True
            detalle = doc.add_paragraph(
                f"Título en pantalla: «{cita.titulo}»"
                + (f" · Autor: {cita.autor}" if cita.autor else "")
                + (f" · {cita.anio}" if cita.anio else "")
            )
            detalle.runs[0].italic = True

        texto = limpiar_para_lectura(intervencion.texto) if limpiar else intervencion.texto
        parrafo = doc.add_paragraph()
        sello = parrafo.add_run(f"[{marca_tiempo(intervencion.start_time)}] ")
        sello.font.size = Pt(8)
        sello.italic = True
        sello.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        quien = parrafo.add_run(f"{_etiqueta(intervencion, identidades, ya_presentados)}\n")
        quien.bold = True
        parrafo.add_run(texto)

        if cita_abierta is not None and cita is None:
            fin = doc.add_paragraph()
            fin.add_run(
                f"[{marca_tiempo(intervencion.start_time)}] FIN — LECTURA DE TEXTO"
            ).bold = True
            cita_abierta = None


def escribir_docx(
    destino: Path,
    contexto: Contexto,
    intervenciones: list[Intervencion],
    identidades: list[Identidad],
    citas: Sequence[CitaEnPantalla],
    limpiar: bool,
) -> Path:
    subtitulo = (
        "Transcripción editorial (versión de lectura)"
        if limpiar
        else "Transcripción literal (sin editar)"
    )
    doc = _nuevo_docx(contexto, subtitulo, identidades)
    _escribir_cuerpo(doc, intervenciones, {i.speaker_label: i for i in identidades}, citas, limpiar)
    doc.save(str(destino))
    return destino


def escribir_txt(
    destino: Path,
    contexto: Contexto,
    intervenciones: list[Intervencion],
    identidades: list[Identidad],
) -> Path:
    indice = {i.speaker_label: i for i in identidades}
    ya: set[str] = set()
    lineas = [contexto.titulo, "=" * len(contexto.titulo), ""]
    if contexto.url:
        lineas.append(f"Fuente: {contexto.url}")
    lineas += [f"Duración: {marca_tiempo(contexto.duracion_s)}", "", ADVERTENCIA, "", "-" * 70, ""]
    for intervencion in intervenciones:
        lineas.append(
            f"[{marca_tiempo(intervencion.start_time)}] {_etiqueta(intervencion, indice, ya)}"
        )
        lineas += [limpiar_para_lectura(intervencion.texto), ""]
    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino


def escribir_srt(
    destino: Path, intervenciones: list[Intervencion], identidades: list[Identidad]
) -> Path:
    indice = {i.speaker_label: i for i in identidades}
    bloques = []
    for numero, intervencion in enumerate(intervenciones, 1):
        identidad = indice.get(intervencion.speaker or "")
        quien = identidad.etiqueta_editorial if identidad else "VOZ NO IDENTIFICADA"
        bloques.append(
            f"{numero}\n"
            f"{marca_tiempo(intervencion.start_time, True)} --> "
            f"{marca_tiempo(intervencion.end_time, True)}\n"
            f"{quien}: {limpiar_para_lectura(intervencion.texto)}\n"
        )
    destino.write_text("\n".join(bloques), encoding="utf-8")
    return destino


def escribir_participantes(destino: Path, identidades: list[Identidad]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Participantes"
    encabezados = [
        "Identificación",
        "Nombre",
        "Función",
        "Institución",
        "ID de voz",
        "Primera aparición",
        "Última aparición",
        "Minutos hablados",
        "Nivel de confianza",
        "Evidencia",
        "Observaciones",
    ]
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.font = Font(bold=True)

    for identidad in identidades:
        hoja.append(
            [
                identidad.etiqueta_editorial,
                identidad.nombre or "",
                identidad.funcion or ("NARRACIÓN" if identidad.es_voz_en_off else ""),
                identidad.institucion or "",
                identidad.speaker_label,
                marca_tiempo(identidad.primera_aparicion),
                marca_tiempo(identidad.ultima_aparicion),
                round(identidad.segundos_hablados / 60, 1),
                identidad.confianza,
                " | ".join(identidad.evidencias) or "Sin evidencia en el video",
                "Voz en off / narración" if identidad.es_voz_en_off else "",
            ]
        )
    for columna, ancho in zip(
        "ABCDEFGHIJK", (28, 24, 26, 14, 12, 16, 16, 16, 14, 70, 24), strict=True
    ):
        hoja.column_dimensions[columna].width = ancho
    libro.save(str(destino))
    return destino


def escribir_citas(destino: Path, citas: Sequence[CitaEnPantalla]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Citas literarias"
    hoja.append(
        [
            "Nº",
            "Inicio",
            "Fin",
            "Título (según pantalla)",
            "Autor",
            "Año",
            "Evidencia",
            "Nivel de confianza",
            "Observaciones",
        ]
    )
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for numero, cita in enumerate(citas, 1):
        hoja.append(
            [
                numero,
                marca_tiempo(cita.inicio_s),
                marca_tiempo(cita.fin_s),
                cita.titulo,
                cita.autor or "No identificado",
                cita.anio or "",
                f"Tarjeta sobreimpresa en {marca_tiempo(cita.inicio_s)}",
                "ALTO" if cita.autor and cita.anio else "MEDIO",
                "El inicio y el fin del pasaje leído requieren cotejo con el audio",
            ]
        )
    for columna, ancho in zip("ABCDEFGHI", (6, 12, 12, 42, 26, 8, 40, 16, 52), strict=True):
        hoja.column_dimensions[columna].width = ancho
    libro.save(str(destino))
    return destino


def escribir_incertidumbres(
    destino: Path,
    identidades: list[Identidad],
    citas: Sequence[CitaEnPantalla],
    segmentos: list[TranscriptSegment],
) -> tuple[Path, int]:
    """Solo lo que necesita decisión humana. Devuelve también cuántos asuntos
    hay: un documento de incertidumbres que nadie cuenta no sirve de nada."""
    lineas = [
        "# Asuntos que requieren revisión humana",
        "",
        "Cada punto es algo que el procesamiento automático **no** pudo resolver "
        "con evidencia suficiente. No se han inventado nombres ni atribuciones.",
        "",
    ]
    asuntos = 0

    sin_nombre = [i for i in identidades if not i.nombre]
    if sin_nombre:
        lineas += ["## Voces sin identificar", ""]
        for identidad in sin_nombre:
            asuntos += 1
            papel = "voz en off / narración" if identidad.es_voz_en_off else "sin función clara"
            lineas += [
                f"### {marca_tiempo(identidad.primera_aparicion)} — {identidad.speaker_label}",
                "",
                f"Habla {identidad.segundos_hablados / 60:.1f} min en total "
                f"(hasta {marca_tiempo(identidad.ultima_aparicion)}). Tratada como {papel}.",
                "",
                "No aparece ningún rótulo sobre sus intervenciones ni se la presenta "
                "en voz alta. Si su nombre figura en los créditos finales, conviene "
                "asignarlo a mano.",
                "",
            ]

    dudosas = [i for i in identidades if i.nombre and i.confianza != "ALTO"]
    if dudosas:
        lineas += ["## Identificaciones que no llegan a confianza alta", ""]
        for identidad in dudosas:
            asuntos += 1
            lineas += [
                f"### {marca_tiempo(identidad.primera_aparicion)} — «{identidad.nombre}» "
                f"({identidad.confianza})",
                "",
                *[f"- {e}" for e in identidad.evidencias],
                "",
            ]

    if citas:
        lineas += ["## Textos leídos en voz alta", ""]
        for cita in citas:
            asuntos += 1
            lineas += [
                f"### {marca_tiempo(cita.inicio_s)} — «{cita.titulo}»",
                "",
                f"Autor según la tarjeta: {cita.autor or 'no identificado'}"
                + (f" ({cita.anio})" if cita.anio else "")
                + ".",
                "",
                "La tarjeta da el título y el autor, pero **no dónde empieza y "
                "termina exactamente la lectura**: eso hay que fijarlo de oído. "
                "Tampoco se ha reconstruido la disposición en versos, que el "
                "reconocimiento de voz no puede deducir de la entonación.",
                "",
            ]

    peores = sorted(
        (s for s in segmentos if s.confidence < CONFIANZA_DUDOSA), key=lambda s: s.confidence
    )[:MAX_PASAJES_DUDOSOS]
    if peores:
        lineas += [
            "## Pasajes con reconocimiento dudoso",
            "",
            f"Los {len(peores)} fragmentos donde el modelo estuvo menos seguro "
            "(de peor a mejor). Suelen ser nombres propios, cifras y siglas: "
            "es donde conviene escuchar antes de publicar.",
            "",
        ]
        for seg in peores:
            asuntos += 1
            lineas.append(
                f"- **{marca_tiempo(seg.start_time)}** (confianza {seg.confidence:.0%}): "
                f"«{seg.clean_text.strip()}»"
            )
        lineas.append("")

    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino, asuntos


def escribir_proceso_tecnico(
    destino: Path,
    contexto: Contexto,
    identidades: list[Identidad],
    citas: Sequence[CitaEnPantalla],
    segmentos: list[TranscriptSegment],
    n_rotulos: int,
) -> Path:
    identificadas = [i for i in identidades if i.nombre]
    lineas = [
        "# Proceso técnico",
        "",
        "## Material",
        "",
        f"- Archivo: `{contexto.archivo}`",
        f"- Duración: {marca_tiempo(contexto.duracion_s)}",
        f"- Fuente: {contexto.url or 'no consignada'}",
        f"- Canal / autor: {contexto.canal or 'no consignado'}",
        f"- Publicado: {contexto.publicado or 'no consignado'}",
        "",
        "## Herramientas",
        "",
        f"- Transcripción: **{contexto.modelo_transcripcion}**, local, sin API.",
        f"- Separación de voces: **{contexto.modelo_diarizacion}**, local, sin API.",
        f"- Lectura de rótulos: **{contexto.modelo_ocr}** sobre fotogramas extraídos con PyAV.",
        "- Decodificación de audio y video: PyAV (no requiere ffmpeg instalado).",
        "- Documentos: python-docx y openpyxl.",
        "- Coste de API: **0 USD**. Todo el procesamiento corrió en esta máquina.",
        "",
        "## Resultados",
        "",
        f"- Segmentos de habla transcritos: {len(segmentos)}",
        f"- Voces distinguidas: {len(identidades)}",
        f"- Voces con nombre propio: {len(identificadas)}",
        f"- Voces sin identificar: {len(identidades) - len(identificadas)}",
        f"- Rótulos leídos en pantalla: {n_rotulos}",
        f"- Textos literarios anunciados por tarjeta: {len(citas)}",
        "",
        "## Cómo se identificó a cada persona",
        "",
        "El nombre NO sale del audio: sale de cruzar los turnos de voz con los "
        "rótulos sobreimpresos. Cada rótulo se lee muchas veces (un fotograma "
        "por segundo) y se consolida por consenso, porque el OCR de un "
        "fotograma suelto es poco fiable: el mismo rótulo puede leerse "
        "«SOLEDAD BIANCHI» en un cuadro y «%LEDAD BIANCHI» en el siguiente.",
        "",
        "Una identificación llega a confianza ALTA solo si el rótulo trae "
        "nombre y cargo, aparece mientras esa voz habla, y ningún otro rótulo "
        "reclama el mismo nombre para otra voz.",
        "",
        "## Límites conocidos",
        "",
        "- **Habla superpuesta**: cuando dos personas hablan a la vez, el tramo "
        "se atribuye a una sola voz. El método (embeddings de voz + "
        "agrupamiento) no separa voces simultáneas.",
        "- **Créditos finales**: no se han cruzado automáticamente con las voces "
        "sin identificar; es la vía más probable para resolverlas.",
        "- **Versos**: la disposición en versos de un texto leído no se puede "
        "deducir del audio. Los pasajes se marcan, no se versifican.",
        "- La transcripción **no ha sido cotejada con el audio por una persona**.",
        "",
    ]
    if contexto.notas:
        lineas += ["## Notas de esta ejecución", "", *[f"- {n}" for n in contexto.notas], ""]
    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino


def generar_paquete(
    carpeta: str | Path,
    contexto: Contexto,
    segmentos: list[TranscriptSegment],
    identidades: list[Identidad],
    citas: Sequence[CitaEnPantalla],
    n_rotulos: int = 0,
) -> dict[str, Path]:
    """Escribe los ocho documentos y devuelve sus rutas."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    intervenciones = construir_intervenciones(segmentos)

    salidas: dict[str, Path] = {}
    salidas["literal"] = escribir_docx(
        carpeta / "transcripcion_literal.docx", contexto, intervenciones, identidades, citas, False
    )
    salidas["limpia"] = escribir_docx(
        carpeta / "transcripcion_limpia.docx", contexto, intervenciones, identidades, citas, True
    )
    salidas["txt"] = escribir_txt(
        carpeta / "transcripcion_completa.txt", contexto, intervenciones, identidades
    )
    salidas["srt"] = escribir_srt(carpeta / "subtitulos.srt", intervenciones, identidades)
    salidas["participantes"] = escribir_participantes(
        carpeta / "participantes_identificados.xlsx", identidades
    )
    salidas["citas"] = escribir_citas(carpeta / "citas_literarias.xlsx", citas)
    salidas["incertidumbres"], asuntos = escribir_incertidumbres(
        carpeta / "incertidumbres.md", identidades, citas, segmentos
    )
    contexto.notas.append(f"{asuntos} asuntos consignados en incertidumbres.md")
    salidas["proceso"] = escribir_proceso_tecnico(
        carpeta / "proceso_tecnico.md", contexto, identidades, citas, segmentos, n_rotulos
    )
    return salidas
