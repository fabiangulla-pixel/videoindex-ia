"""Reproductor con salto a timestamp — Video Navigation Engine del SAD.

Lección del smoke test E0 (esta máquina, Win10): con el backend ffmpeg de Qt
el render de QVideoWidget crashea; con QT_MEDIA_BACKEND=windows (WMF) funciona.
app.py fija esa variable ANTES de crear la QApplication. Además, el seek debe
hacerse DESPUÉS de que play() arranca, o WMF lo pisa.
"""

from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_COLCHON_MS = 2000  # abre 2 s antes del timestamp pedido (margen de la spec)


def _fmt(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_s(segundos: float) -> str:
    return _fmt(int(segundos * 1000))


class PlayerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.video = QVideoWidget(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)

        self.titulo = QLabel("Sin video")
        self.titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.boton_play = QPushButton("⏸")
        self.boton_play.setFixedWidth(44)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.tiempo = QLabel("00:00:00 / 00:00:00")

        controles = QHBoxLayout()
        controles.addWidget(self.boton_play)
        controles.addWidget(self.slider, stretch=1)
        controles.addWidget(self.tiempo)

        # Notas manuales del usuario ligadas a este video (independientes
        # del pipeline de IA): "aquí se habla de X". 100% local, en SQLite.
        self.boton_anotar = QPushButton("📝 Anotar aquí")
        self.boton_anotar.setEnabled(False)  # sin video abierto, no hay dónde anotar
        self.boton_anotar.clicked.connect(self._anotar_en_posicion_actual)

        # Salta el negro/silencio inicial detectado en el pipeline (nunca
        # modifica el archivo; solo mueve el punto de reproducción).
        self.boton_saltar_contenido = QPushButton("⏭ Saltar al inicio del contenido")
        self.boton_saltar_contenido.setEnabled(False)
        self.boton_saltar_contenido.clicked.connect(self._saltar_al_inicio_contenido)

        self.lista_notas = QListWidget()
        self.lista_notas.setMaximumHeight(120)
        self.lista_notas.itemDoubleClicked.connect(self._saltar_a_nota)
        self.lista_notas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista_notas.customContextMenuRequested.connect(self._menu_notas)

        layout = QVBoxLayout(self)
        layout.addWidget(self.titulo)
        layout.addWidget(self.video, stretch=1)
        layout.addLayout(controles)
        layout.addWidget(self.boton_saltar_contenido)
        layout.addWidget(self.boton_anotar)
        layout.addWidget(QLabel("Notas (doble clic para saltar, clic derecho para editar/borrar):"))
        layout.addWidget(self.lista_notas)

        self.boton_play.clicked.connect(self._toggle)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))

        self._ruta_actual: str | None = None
        self._video_id_actual: str | None = None
        self._content_start_actual: float | None = None

    def abrir_en(
        self, ruta: str, titulo: str, start_time_s: float, video_id: str | None = None
    ) -> None:
        """Abre el video y salta al instante exacto (menos el colchón).

        video_id es opcional (SearchView aún no lo pasa) — sin él, el botón
        de anotar queda deshabilitado porque no hay a qué video ligar la nota.
        """
        destino_ms = max(0, int(start_time_s * 1000) - _COLCHON_MS)
        self.titulo.setText(titulo)
        if self._ruta_actual != ruta:
            self._ruta_actual = ruta
            self.player.setSource(QUrl.fromLocalFile(ruta))
        self.player.play()
        # WMF: el seek va después de que la reproducción arranca (lección E0)
        QTimer.singleShot(300, lambda: self.player.setPosition(destino_ms))
        self.boton_play.setText("⏸")

        self._video_id_actual = video_id
        self.boton_anotar.setEnabled(video_id is not None)
        self._cargar_notas()
        self._cargar_content_start()

    def _cargar_notas(self) -> None:
        self.lista_notas.clear()
        if not self._video_id_actual:
            return
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import AnnotationRepo

        con = conectar(paths.DB_PATH)
        try:
            notas = AnnotationRepo(con).por_video(self._video_id_actual)
        finally:
            con.close()
        for nota in notas:
            item = QListWidgetItem(f"{_fmt_s(nota.timestamp_s)} — {nota.text}")
            item.setData(Qt.ItemDataRole.UserRole, nota)
            self.lista_notas.addItem(item)

    def _cargar_content_start(self) -> None:
        self._content_start_actual = None
        self.boton_saltar_contenido.setEnabled(False)
        if not self._video_id_actual:
            return
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import VideoRepo

        con = conectar(paths.DB_PATH)
        try:
            video = VideoRepo(con).por_id(self._video_id_actual)
        finally:
            con.close()
        # None (aún no detectado) y 0.0 (no se detectó negro) quedan
        # deshabilitados por igual: no hay a dónde saltar en ambos casos.
        if video and video.content_start_s:
            self._content_start_actual = video.content_start_s
            self.boton_saltar_contenido.setEnabled(True)

    def _saltar_al_inicio_contenido(self) -> None:
        if self._content_start_actual is None:
            return
        self.player.setPosition(int(self._content_start_actual * 1000))

    def _anotar_en_posicion_actual(self) -> None:
        if not self._video_id_actual:
            return
        texto, ok = QInputDialog.getMultiLineText(
            self, "Nueva nota", "¿Qué se dice/muestra en este instante del video?"
        )
        texto = texto.strip()
        if not ok or not texto:
            return

        from videoindex.config import paths
        from videoindex.domain.models import Annotation
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import AnnotationRepo

        nota = Annotation(
            annotation_id=str(uuid4()),
            video_id=self._video_id_actual,
            timestamp_s=self.player.position() / 1000,
            text=texto,
        )
        con = conectar(paths.DB_PATH)
        try:
            AnnotationRepo(con).guardar(nota)
        finally:
            con.close()
        self._cargar_notas()

    def _saltar_a_nota(self, item: QListWidgetItem) -> None:
        nota = item.data(Qt.ItemDataRole.UserRole)
        self.player.setPosition(int(nota.timestamp_s * 1000))

    def _menu_notas(self, pos) -> None:
        item = self.lista_notas.itemAt(pos)
        if item is None:
            return
        nota = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        accion_editar = menu.addAction("Editar")
        accion_borrar = menu.addAction("Borrar")
        elegida = menu.exec(self.lista_notas.mapToGlobal(pos))
        if elegida == accion_editar:
            self._editar_nota(nota)
        elif elegida == accion_borrar:
            self._borrar_nota(nota)

    def _editar_nota(self, nota) -> None:
        texto, ok = QInputDialog.getMultiLineText(self, "Editar nota", "Texto:", nota.text)
        texto = texto.strip()
        if not ok or not texto:
            return
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import AnnotationRepo

        con = conectar(paths.DB_PATH)
        try:
            AnnotationRepo(con).actualizar_texto(nota.annotation_id, texto)
        finally:
            con.close()
        self._cargar_notas()

    def _borrar_nota(self, nota) -> None:
        if (
            QMessageBox.question(self, "Borrar nota", "¿Eliminar esta nota?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import AnnotationRepo

        con = conectar(paths.DB_PATH)
        try:
            AnnotationRepo(con).eliminar(nota.annotation_id)
        finally:
            con.close()
        self._cargar_notas()

    def _toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.boton_play.setText("▶")
        else:
            self.player.play()
            self.boton_play.setText("⏸")

    def _on_pos(self, pos: int):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.tiempo.setText(f"{_fmt(pos)} / {_fmt(self.player.duration())}")
