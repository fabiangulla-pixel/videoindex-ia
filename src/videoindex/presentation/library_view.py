"""Biblioteca e ingesta: agregar carpeta → resumen con ETA → confirmar → progreso."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from videoindex.application.time_estimator import TimeEstimator
from videoindex.config.settings import SETTINGS
from videoindex.presentation.dossier_view import DossierConfirmDialog, DossierResultDialog
from videoindex.presentation.workers import (
    DescargaWorker,
    DossierGenerarWorker,
    DossierRecopilarWorker,
    EliminarVideoWorker,
    EscaneoWorker,
    PipelineWorker,
    TrimWorker,
)

_ETIQUETAS_ESTADO = {
    "pending": "⏳ pendiente",
    "transcribing": "🎙 transcribiendo",
    # Etapa de progreso, no estado persistido (ver PipelineService._diarizar).
    "diarizing": "🗣 separando voces",
    "segmenting": "✂ segmentando",
    "extracting": "🏷 entidades",
    "indexing": "📇 indexando",
    "completed": "✅ completado",
    "failed": "❌ falló",
}


class LibraryView(QWidget):
    # path, título, timestamp inicial (0 = desde el principio), video_id
    abrir_video = Signal(str, str, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boton_agregar = QPushButton("📂 Agregar carpeta…")
        self.boton_url = QPushButton("🌐 Añadir desde URL…")
        self.boton_url.setToolTip(
            "Baja la pista de audio de un video de YouTube (u otro sitio) y lo "
            "añade a la biblioteca con su título, canal y fecha reales"
        )
        self.boton_continuar = QPushButton("▶ Continuar procesando")
        self.boton_continuar.setVisible(False)  # solo si hay pendientes (ver refrescar())
        self.boton_exportar = QPushButton("📦 Exportar corpus…")
        self.boton_exportar.setToolTip(
            "Exporta un JSON por video completado de la vista actual "
            "(chunks con timestamps, entidades y anotaciones)"
        )
        self.boton_exportar_okf = QPushButton("🗂 Exportar bundle OKF…")
        self.boton_exportar_okf.setToolTip(
            "Exporta la vista actual como bundle OKF (Open Knowledge Format): "
            "markdown + frontmatter por video y por entidad, enlazados entre sí, "
            "para que otro agente de IA lo lea sin depender de esta app"
        )
        self.progreso = QProgressBar()
        self.progreso.setVisible(False)
        self.etiqueta_estado = QLabel("")

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Título", "Proyecto", "Curso", "Duración", "Estado"])
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.itemDoubleClicked.connect(self._abrir_seleccionado)
        self.tabla.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setPlaceholderText(
            "El registro de actividad (qué archivo se procesa, en qué etapa) aparece aquí…"
        )
        self.log.setFixedHeight(120)

        barra = QHBoxLayout()
        barra.addWidget(self.boton_agregar)
        barra.addWidget(self.boton_url)
        barra.addWidget(self.boton_continuar)
        barra.addWidget(self.boton_exportar)
        barra.addWidget(self.boton_exportar_okf)
        barra.addWidget(self.etiqueta_estado, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.progreso)
        layout.addWidget(self.tabla, stretch=1)
        layout.addWidget(QLabel("Registro de actividad:"))
        layout.addWidget(self.log)

        self.boton_agregar.clicked.connect(self._agregar_carpeta)
        self.boton_url.clicked.connect(self._agregar_desde_url)
        self.boton_continuar.clicked.connect(self.continuar_procesando)
        self.boton_exportar.clicked.connect(self._exportar_corpus_proyecto)
        self.boton_exportar_okf.clicked.connect(self._exportar_okf_proyecto)
        self._worker = None
        self._worker_dossier = None  # flujo independiente de la ingesta
        self._worker_eliminar = None  # flujo independiente de la ingesta
        self._dialogo_transcripcion = None  # ventana no-modal: hay que retenerla
        # Mismo sentinel que VideoRepo.listar(project_id=...): "__todos__" no
        # filtra, None filtra por "sin proyecto", cualquier otro string es
        # un project_id real.
        self._proyecto_activo: str | None = "__todos__"
        # Proyecto al que se asignan los videos NUEVOS al escanear una
        # carpeta (None si el filtro activo es "Todos" o "Sin proyecto").
        # Lo setea MainWindow junto con filtrar_por_proyecto.
        self.proyecto_para_ingesta: str | None = None
        self._ultima_etapa_registrada: tuple[str, str] | None = None
        self.refrescar()

    def filtrar_por_proyecto(self, project_id: str | None) -> None:
        """Conectado a ProjectSelector.proyecto_cambiado."""
        self._proyecto_activo = project_id
        self.refrescar()

    def _registrar(self, mensaje: str) -> None:
        self.log.appendPlainText(mensaje)

    def refrescar(self):
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import ProjectRepo, VideoRepo

        con = conectar(paths.DB_PATH)
        try:
            videos = VideoRepo(con).listar(self._proyecto_activo)
            nombres_proyecto = {p.project_id: p.name for p in ProjectRepo(con).listar()}
            n_pendientes = len(VideoRepo(con).pendientes())
        finally:
            con.close()
        # Visible solo si hay algo que continuar: no tiene sentido el botón
        # en una biblioteca donde todo ya está "completed".
        self.boton_continuar.setVisible(n_pendientes > 0)
        if n_pendientes > 0:
            self.boton_continuar.setText(f"▶ Continuar procesando ({n_pendientes})")
        self.tabla.setRowCount(len(videos))
        for fila, v in enumerate(videos):
            dur = TimeEstimator.humano(v.duration_seconds or 0)
            for col, texto in enumerate(
                [
                    v.title,
                    nombres_proyecto.get(v.project_id, "—"),
                    v.course_name or "—",
                    dur,
                    _ETIQUETAS_ESTADO.get(v.processing_status, v.processing_status),
                ]
            ):
                item = QTableWidgetItem(texto)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, (v.video_id, v.path))
                self.tabla.setItem(fila, col, item)

    def _abrir_seleccionado(self, item: QTableWidgetItem) -> None:
        """Reproducir cualquier video de la biblioteca, esté o no procesado
        (pedido explícito: no limitar la reproducción a resultados de
        búsqueda)."""
        fila = item.row()
        item_titulo = self.tabla.item(fila, 0)
        if item_titulo is None:
            return
        video_id, ruta = item_titulo.data(Qt.ItemDataRole.UserRole)
        self.abrir_video.emit(ruta, item_titulo.text(), 0.0, video_id)

    def _menu_contextual(self, pos) -> None:
        item = self.tabla.itemAt(pos)
        if item is None:
            return
        fila = item.row()
        item_titulo = self.tabla.item(fila, 0)
        estado_item = self.tabla.item(fila, 4)
        if item_titulo is None or estado_item is None:
            return
        video_id, _ruta = item_titulo.data(Qt.ItemDataRole.UserRole)
        proyecto_item = self.tabla.item(fila, 1)
        tiene_proyecto = proyecto_item is not None and proyecto_item.text() != "—"

        menu = QMenu(self)
        accion_transcripcion = menu.addAction("🗣 Transcripción y hablantes…")
        accion_transcripcion.setEnabled(estado_item.text() == _ETIQUETAS_ESTADO["completed"])
        accion_dossier = menu.addAction("📄 Generar dossier del video…")
        # Sin chunks (video no completado) no hay nada que agrupar por entidad.
        accion_dossier.setEnabled(estado_item.text() == _ETIQUETAS_ESTADO["completed"])
        accion_recortar = menu.addAction("✂ Recortar antes de transcribir…")
        # Recortar un video ya transcrito invalidaría sus timestamps: el
        # recorte es para ANTES de pagar el tiempo de transcripción.
        accion_recortar.setEnabled(
            estado_item.text() in (_ETIQUETAS_ESTADO["pending"], _ETIQUETAS_ESTADO["failed"])
        )
        accion_exportar = menu.addAction("📦 Exportar corpus JSON…")
        accion_exportar.setEnabled(estado_item.text() == _ETIQUETAS_ESTADO["completed"])
        accion_exportar_okf = menu.addAction("🗂 Exportar bundle OKF…")
        accion_exportar_okf.setEnabled(estado_item.text() == _ETIQUETAS_ESTADO["completed"])
        menu.addSeparator()
        accion_desasignar = menu.addAction("📤 Quitar del proyecto")
        accion_desasignar.setEnabled(tiene_proyecto)
        accion_eliminar = menu.addAction("🗑 Eliminar de la biblioteca…")
        elegida = menu.exec(self.tabla.viewport().mapToGlobal(pos))
        if elegida == accion_transcripcion:
            self._abrir_transcripcion(video_id, item_titulo.text(), _ruta)
        elif elegida == accion_dossier:
            self._iniciar_dossier(video_id, item_titulo.text())
        elif elegida == accion_recortar:
            self._recortar_video(video_id, _ruta, item_titulo.text())
        elif elegida == accion_exportar:
            self._exportar_corpus_video(video_id, item_titulo.text())
        elif elegida == accion_exportar_okf:
            self._exportar_okf_video(video_id, item_titulo.text())
        elif elegida == accion_desasignar:
            self._desasignar_proyecto(video_id)
        elif elegida == accion_eliminar:
            self._confirmar_eliminar(video_id, item_titulo.text())

    def _abrir_transcripcion(self, video_id: str, titulo: str, ruta: str) -> None:
        """La ventana de transcripción es no-modal a propósito: se usa CONTRA
        el reproductor (doble clic en una intervención salta a ese minuto para
        verificarla de oído), así que ambos tienen que estar vivos a la vez."""
        from videoindex.presentation.transcript_dialog import TranscriptDialog

        dialogo = TranscriptDialog(video_id, titulo, self)
        dialogo.setModal(False)
        dialogo.saltar_a.connect(
            lambda segundo: self.abrir_video.emit(ruta, titulo, segundo, video_id)
        )
        dialogo.show()
        # Sin esta referencia el diálogo no-modal se destruiría al salir del
        # método (queda sin dueño fuerte en Python) y desaparecería solo.
        self._dialogo_transcripcion = dialogo

    def _exportar_corpus_video(self, video_id: str, titulo: str) -> None:
        from videoindex.application.export_service import exportar_video_json
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar

        destino, _ = QFileDialog.getSaveFileName(
            self, "Exportar corpus del video", f"{titulo}.json", "JSON (*.json)"
        )
        if not destino:
            return
        con = conectar(paths.DB_PATH)
        try:
            ruta = exportar_video_json(con, video_id, destino)
        except Exception as exc:
            self._error(str(exc))
            return
        finally:
            con.close()
        self._registrar(f"Corpus exportado: {ruta}")
        self.etiqueta_estado.setText(f"Corpus exportado a {ruta}")

    def _exportar_corpus_proyecto(self) -> None:
        from videoindex.application.export_service import exportar_proyecto_json
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar

        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta destino del corpus")
        if not carpeta:
            return
        con = conectar(paths.DB_PATH)
        try:
            escritos = exportar_proyecto_json(con, self._proyecto_activo, carpeta)
        except Exception as exc:
            self._error(str(exc))
            return
        finally:
            con.close()
        if not escritos:
            QMessageBox.information(
                self,
                "Exportar corpus",
                "No hay videos completados en la vista actual: nada que exportar.",
            )
            return
        self._registrar(f"Corpus del proyecto exportado: {len(escritos)} JSON en {carpeta}")
        self.etiqueta_estado.setText(f"Corpus exportado: {len(escritos)} archivo(s) en {carpeta}")

    def _exportar_okf_video(self, video_id: str, titulo: str) -> None:
        from videoindex.application.okf_export_service import exportar_video_okf
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar

        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta destino del bundle OKF")
        if not carpeta:
            return
        nombre_seguro = "".join(c if c.isalnum() or c in " _-." else "_" for c in titulo)
        destino = Path(carpeta) / f"{nombre_seguro}_okf"
        con = conectar(paths.DB_PATH)
        try:
            escritos = exportar_video_okf(con, video_id, destino)
        except Exception as exc:
            self._error(str(exc))
            return
        finally:
            con.close()
        self._registrar(f"Bundle OKF exportado: {len(escritos)} archivo(s) en {destino}")
        self.etiqueta_estado.setText(f"Bundle OKF exportado a {destino}")

    def _exportar_okf_proyecto(self) -> None:
        from videoindex.application.okf_export_service import exportar_proyecto_okf
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar

        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta destino del bundle OKF")
        if not carpeta:
            return
        con = conectar(paths.DB_PATH)
        try:
            escritos = exportar_proyecto_okf(con, self._proyecto_activo, carpeta)
        except Exception as exc:
            self._error(str(exc))
            return
        finally:
            con.close()
        if len(escritos) <= 1:  # solo index.md vacío: ningún video completado en la vista
            QMessageBox.information(
                self,
                "Exportar bundle OKF",
                "No hay videos completados en la vista actual: nada que exportar.",
            )
            return
        self._registrar(
            f"Bundle OKF del proyecto exportado: {len(escritos)} archivo(s) en {carpeta}"
        )
        self.etiqueta_estado.setText(
            f"Bundle OKF exportado: {len(escritos)} archivo(s) en {carpeta}"
        )

    def _recortar_video(self, video_id: str, ruta: str, titulo: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Recortar", "Espera a que termine el proceso en curso.")
            return
        from videoindex.presentation.trim_dialog import TrimDialog

        dialogo = TrimDialog(ruta, titulo, self)
        if dialogo.exec() != TrimDialog.DialogCode.Accepted:
            return
        inicio_s, fin_s = dialogo.rango_seleccionado()

        self.etiqueta_estado.setText(f'Recortando "{titulo}"…')
        self._registrar(f'Recortando "{titulo}" ({inicio_s:.0f}s → {fin_s or "final"})')
        self.progreso.setVisible(True)
        self.progreso.setRange(0, 100)
        self._worker = TrimWorker(video_id, ruta, inicio_s, fin_s)
        self._worker.progreso.connect(lambda f: self.progreso.setValue(int(f * 100)))
        self._worker.terminado.connect(self._on_recortado)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _on_recortado(self, titulo_nuevo: str) -> None:
        self.progreso.setVisible(False)
        self.etiqueta_estado.setText(f'Recorte listo: "{titulo_nuevo}" reemplazó al original.')
        self._registrar(
            f'Recorte listo: "{titulo_nuevo}" entró a la biblioteca (pendiente de '
            "transcribir); el original salió de la lista, su archivo en disco no se tocó."
        )
        self.refrescar()

    def _desasignar_proyecto(self, video_id: str) -> None:
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import VideoRepo

        con = conectar(paths.DB_PATH)
        try:
            VideoRepo(con).asignar_proyecto(video_id, None)
        finally:
            con.close()
        self.refrescar()

    def _confirmar_eliminar(self, video_id: str, titulo: str) -> None:
        if self._worker_eliminar is not None and self._worker_eliminar.isRunning():
            return  # guardia anti-doble-disparo
        respuesta = QMessageBox.question(
            self,
            "Eliminar video",
            f'¿Eliminar "{titulo}" de la biblioteca?\n\n'
            "Se borra la transcripción, los fragmentos indexados, entidades y "
            "anotaciones. El archivo de video en disco NO se toca.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        self.etiqueta_estado.setText(f'Eliminando "{titulo}"…')
        self._registrar(f'Eliminando de la biblioteca: "{titulo}"')
        self._worker_eliminar = EliminarVideoWorker(video_id)
        self._worker_eliminar.terminado.connect(self._on_eliminado)
        self._worker_eliminar.fallo.connect(self._error)
        self._worker_eliminar.start()

    def _on_eliminado(self, video_id: str) -> None:
        self.etiqueta_estado.setText("Video eliminado de la biblioteca.")
        self._registrar(f"[{video_id[:8]}] eliminado de la biblioteca.")
        self.refrescar()

    def _iniciar_dossier(self, video_id: str, titulo: str) -> None:
        if self._worker_dossier is not None and self._worker_dossier.isRunning():
            return  # guardia anti-doble-disparo
        self._worker_dossier = DossierRecopilarWorker(video_id, titulo)
        self._worker_dossier.listo.connect(self._confirmar_costo_dossier)
        self._worker_dossier.fallo.connect(self._error)
        self._worker_dossier.start()

    def _confirmar_costo_dossier(self, titulo: str, entidades_evidencia: list) -> None:
        if not entidades_evidencia:
            QMessageBox.information(
                self, "Dossier", "No se detectaron entidades en este video: nada que agrupar."
            )
            return

        dialogo = DossierConfirmDialog(len(entidades_evidencia), self)
        if dialogo.exec() != DossierConfirmDialog.DialogCode.Accepted:
            return
        proveedor, modelo = dialogo.proveedor_modelo()

        from videoindex.application.dossier_service import DossierService
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar

        con = conectar(paths.DB_PATH)
        try:
            servicio = DossierService(con, SETTINGS.rag)
            estimacion = servicio.estimar_dossier(entidades_evidencia, proveedor, modelo)
        except Exception as exc:
            con.close()
            self._error(str(exc))
            return
        con.close()

        if not estimacion.es_local and (
            QMessageBox.question(
                self,
                "Confirmar gasto de IA",
                estimacion.resumen(),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        self._worker_dossier = DossierGenerarWorker(titulo, entidades_evidencia, proveedor, modelo)
        self._worker_dossier.listo.connect(self._mostrar_dossier)
        self._worker_dossier.fallo.connect(self._error)
        self._worker_dossier.start()

    def _mostrar_dossier(self, titulo: str, dossier: list, costo_real) -> None:
        from videoindex.application.dossier_service import DossierService

        markdown = DossierService.exportar_markdown(titulo, dossier)
        DossierResultDialog(titulo, markdown, costo_real.resumen(), self).exec()

    def _agregar_carpeta(self):
        if self._worker is not None and self._worker.isRunning():
            return  # guardia: ya hay un escaneo/lote en curso
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta con videos o audios")
        if not carpeta:
            return
        self.etiqueta_estado.setText("Escaneando carpeta (checksums)…")
        self._registrar(f"Escaneando: {carpeta}")
        self.boton_agregar.setEnabled(False)  # guardia anti-doble-clic
        self.progreso.setVisible(True)
        self.progreso.setRange(0, 0)  # indeterminada hasta saber el total de archivos
        self._worker = EscaneoWorker(carpeta, project_id=self.proyecto_para_ingesta)
        self._worker.progreso.connect(self._on_progreso_escaneo)
        self._worker.terminado.connect(self._confirmar_lote)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _agregar_desde_url(self):
        if self._worker is not None and self._worker.isRunning():
            return  # guardia: ya hay un escaneo/descarga/lote en curso
        from videoindex.presentation.url_dialog import UrlDialog

        dialogo = UrlDialog(self)
        if dialogo.exec() != UrlDialog.DialogCode.Accepted:
            return
        urls = dialogo.urls()
        if not urls:
            return

        self.etiqueta_estado.setText(f"Descargando {len(urls)} URL(s)…")
        self._registrar(f"Descarga desde URL: {len(urls)} enlace(s)")
        self.boton_url.setEnabled(False)  # guardia anti-doble-clic
        self.boton_agregar.setEnabled(False)
        self.progreso.setVisible(True)
        self.progreso.setRange(0, 0)  # yt-dlp no siempre sabe el total: indeterminada
        self._worker = DescargaWorker(urls, project_id=self.proyecto_para_ingesta)
        self._worker.progreso.connect(self._on_progreso_descarga)
        self._worker.terminado.connect(self._on_descargado)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _on_progreso_descarga(self, indice: int, total: int, mensaje: str):
        self.etiqueta_estado.setText(f"[{indice}/{total}] {mensaje}")

    def _on_descargado(self, resultado, errores: list):
        self.boton_url.setEnabled(True)
        self.progreso.setVisible(False)
        for error in errores:
            self._registrar(f"ERROR descargando — {error}")
        for video in resultado.nuevos:
            self._registrar(f"Descargado y añadido: «{video.title}»")
        if errores and not resultado.por_procesar:
            self.boton_agregar.setEnabled(True)
            self.etiqueta_estado.setText("Ninguna descarga se pudo completar.")
            QMessageBox.warning(self, "Descarga desde URL", "\n\n".join(errores))
            return
        if errores:
            QMessageBox.warning(
                self,
                "Descarga desde URL",
                "Algunas URLs fallaron; el resto sí se descargó:\n\n" + "\n\n".join(errores),
            )
        self._confirmar_lote(resultado)

    def _on_progreso_escaneo(self, indice: int, total: int, nombre: str):
        self.progreso.setRange(0, total)
        self.progreso.setValue(indice)
        self.etiqueta_estado.setText(f"Calculando checksum {indice}/{total}…")
        self._registrar(f"[{indice}/{total}] checksum: {nombre}")

    def _confirmar_lote(self, resultado):
        self.refrescar()
        self.progreso.setVisible(False)
        por_procesar = resultado.por_procesar
        if not por_procesar:
            self.etiqueta_estado.setText("Nada nuevo que procesar.")
            self._registrar("Escaneo terminado: nada nuevo que procesar.")
            self.boton_agregar.setEnabled(True)
            self.boton_url.setEnabled(True)
            return
        self._confirmar_y_procesar(por_procesar)

    def continuar_procesando(self):
        if self._worker is not None and self._worker.isRunning():
            return  # guardia: ya hay un escaneo/lote en curso
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import VideoRepo

        con = conectar(paths.DB_PATH)
        try:
            pendientes = VideoRepo(con).pendientes()
        finally:
            con.close()
        if not pendientes:
            self.refrescar()  # oculta el botón si ya no hay pendientes
            return
        self._confirmar_y_procesar(pendientes)

    def _confirmar_y_procesar(self, videos) -> None:
        """Compartido por 'Agregar carpeta' (tras escanear) y 'Continuar
        procesando' (sobre lo ya pendiente en la biblioteca, sin re-escanear
        ninguna carpeta): mismo diálogo de ETA/costo y el mismo PipelineWorker."""
        from videoindex.config.settings import factor_tiempo

        diarizacion = SETTINGS.diarization.activa
        estimador = TimeEstimator(factor_tiempo(SETTINGS.transcription.modelo, diarizacion))
        horas = sum(v.duration_seconds or 0.0 for v in videos) / 3600
        eta = estimador.eta_lote([v.duration_seconds or 0 for v in videos])
        if diarizacion:
            cuantos = SETTINGS.diarization.n_hablantes
            hablantes = f"{cuantos} hablantes fijos" if cuantos else "número automático"
            linea_voces = f"Separación de voces: sí ({hablantes})\n"
        else:
            linea_voces = "Separación de voces: no (actívala en Configuración)\n"
        detalle = (
            f"Videos por procesar: {len(videos)}\n"
            f"Material: {horas:.1f} horas\n\n"
            f"Costo API: $0 (transcripción, voces y embeddings 100% locales)\n"
            f"Tiempo estimado: ~{TimeEstimator.humano(eta)} "
            f"(whisper {SETTINGS.transcription.modelo}, CPU)\n"
            f"{linea_voces}\n"
            "¿Procesar ahora? Puedes cerrar la app a mitad: al relanzar se reanuda."
        )
        if (
            QMessageBox.question(self, "Confirmar procesamiento", detalle)
            != QMessageBox.StandardButton.Yes
        ):
            self.etiqueta_estado.setText("Lote registrado como pendiente (no procesado).")
            self.boton_agregar.setEnabled(True)
            self.boton_url.setEnabled(True)
            return

        self.progreso.setVisible(True)
        self.progreso.setRange(0, 100)
        self._worker = PipelineWorker([v.video_id for v in videos])
        self._worker.progreso.connect(self._on_progreso)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.fallo.connect(self._error)
        self._worker.start()

    def _on_progreso(self, video_id: str, etapa: str, fraccion: float):
        porcentaje = int(fraccion * 100)
        self.progreso.setValue(porcentaje)
        etiqueta = _ETIQUETAS_ESTADO.get(etapa, etapa)
        self.etiqueta_estado.setText(f"{etiqueta} ({porcentaje}%)")
        # "transcribing" se reporta por cada segmento de habla (decenas/cientos
        # por video): solo se registra en el log y se refresca la tabla en el
        # CAMBIO de etapa, no en cada tick de progreso interno — si no, el log
        # y la recarga de la tabla desde SQLite inundarían la UI.
        clave = (video_id, etapa)
        if clave != self._ultima_etapa_registrada:
            self._ultima_etapa_registrada = clave
            self._registrar(f"[{video_id[:8]}] {etiqueta}")
            self.refrescar()

    def _on_terminado(self, ok: int, fail: int):
        self.progreso.setVisible(False)
        self.etiqueta_estado.setText(f"Lote terminado: {ok} completados, {fail} fallidos.")
        self._registrar(f"Lote terminado: {ok} completados, {fail} fallidos.")
        self.boton_agregar.setEnabled(True)
        self.boton_url.setEnabled(True)
        self.refrescar()

    def _error(self, mensaje: str):
        self.progreso.setVisible(False)
        self.boton_agregar.setEnabled(True)
        self.boton_url.setEnabled(True)
        self._registrar(f"ERROR: {mensaje}")
        QMessageBox.critical(self, "Error", mensaje)
