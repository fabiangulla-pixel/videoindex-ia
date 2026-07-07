"""Ventana principal: pestañas (Biblioteca / Buscar / Preguntar) + reproductor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QSplitter, QTabWidget

from videoindex.presentation.library_view import LibraryView
from videoindex.presentation.player_widget import PlayerWidget
from videoindex.presentation.search_view import SearchView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoIndex IA — conocimiento audiovisual navegable")
        self.resize(1200, 720)

        self.biblioteca = LibraryView()
        self.busqueda = SearchView()
        self.player = PlayerWidget()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.biblioteca, "📚 Biblioteca")
        self.tabs.addTab(self.busqueda, "🔍 Buscar")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.player)
        splitter.setSizes([560, 640])
        self.setCentralWidget(splitter)

        self.busqueda.abrir_video.connect(self.player.abrir_en)
        self.biblioteca.abrir_video.connect(self.player.abrir_en)
        self.preguntar = None

        menu = self.menuBar().addMenu("&Configuración")
        accion_config = QAction("API Keys y modelo por defecto…", self)
        accion_config.triggered.connect(self._abrir_configuracion)
        menu.addAction(accion_config)

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
