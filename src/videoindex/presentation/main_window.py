"""Ventana principal: pestañas (Biblioteca / Buscar / Preguntar) + reproductor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from videoindex.presentation.library_view import LibraryView
from videoindex.presentation.player_widget import PlayerWidget
from videoindex.presentation.project_selector import ProjectSelector
from videoindex.presentation.search_view import SearchView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoIndex IA — conocimiento audiovisual navegable")
        self.resize(1200, 720)

        self.selector_proyecto = ProjectSelector()
        self.biblioteca = LibraryView()
        self.busqueda = SearchView()
        self.player = PlayerWidget()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.biblioteca, "📚 Biblioteca")
        self.tabs.addTab(self.busqueda, "🔍 Buscar")

        barra_proyecto = QHBoxLayout()
        barra_proyecto.addWidget(QLabel("Proyecto:"))
        barra_proyecto.addWidget(self.selector_proyecto)
        barra_proyecto.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.player)
        splitter.setSizes([560, 640])

        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        layout.addLayout(barra_proyecto)
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(contenedor)

        self.busqueda.abrir_video.connect(self.player.abrir_en)
        self.biblioteca.abrir_video.connect(self.player.abrir_en)
        self.selector_proyecto.proyecto_cambiado.connect(self.biblioteca.filtrar_por_proyecto)
        self.selector_proyecto.proyecto_cambiado.connect(self._actualizar_proyecto_ingesta)
        self.biblioteca.proyecto_para_ingesta = self.selector_proyecto.proyecto_para_asignar()
        self.preguntar = None

        menu = self.menuBar().addMenu("&Configuración")
        accion_config = QAction("API Keys y modelo por defecto…", self)
        accion_config.triggered.connect(self._abrir_configuracion)
        menu.addAction(accion_config)

        self._ofrecer_continuar_pendientes()

    def _ofrecer_continuar_pendientes(self) -> None:
        """Si quedaron videos sin 'completed' de una sesión anterior (la app
        se cerró a media transcripción, o el usuario dijo 'no' a procesar un
        lote recién escaneado), preguntar UNA vez al arrancar si retomarlos —
        en vez de dejar que el usuario tenga que notar el botón "Continuar
        procesando" y darle clic él mismo."""
        from videoindex.config import paths
        from videoindex.infrastructure.db.connection import conectar
        from videoindex.infrastructure.db.repositories import VideoRepo

        con = conectar(paths.DB_PATH)
        try:
            n_pendientes = len(VideoRepo(con).pendientes())
        finally:
            con.close()
        if n_pendientes == 0:
            return
        if (
            QMessageBox.question(
                self,
                "Videos pendientes",
                f"Tienes {n_pendientes} video(s) sin terminar de procesar "
                "(de una sesión anterior). ¿Continuar ahora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.biblioteca.continuar_procesando()

    def _actualizar_proyecto_ingesta(self, _dato) -> None:
        self.biblioteca.proyecto_para_ingesta = self.selector_proyecto.proyecto_para_asignar()

    def _abrir_configuracion(self) -> None:
        from videoindex.presentation.settings_dialog import ApiSettingsDialog

        ApiSettingsDialog(self).exec()
        if self.preguntar is not None:
            self.preguntar.refrescar_proveedor_default()

    def agregar_pestana_rag(self, widget) -> None:
        """La pestaña Preguntar se acopla cuando el RAG está configurado (E5)."""
        self.preguntar = widget
        self.tabs.addTab(widget, "💬 Preguntar")

    def closeEvent(self, event) -> None:
        """Espera a que terminen los QThread en curso antes de cerrar: destruir
        un QThread vivo (transcripción, búsqueda, RAG) crashea con
        'QThread: Destroyed while thread is still running'."""
        for vista in (self.biblioteca, self.busqueda, self.preguntar):
            worker = getattr(vista, "_worker", None)
            if worker is not None and worker.isRunning():
                worker.wait(5000)
        super().closeEvent(event)
