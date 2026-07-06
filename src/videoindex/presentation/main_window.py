"""Ventana principal: pestañas (Biblioteca / Buscar / Preguntar) + reproductor."""

from __future__ import annotations

from PySide6.QtCore import Qt
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

    def agregar_pestana_rag(self, widget) -> None:
        """La pestaña Preguntar se acopla cuando el RAG está configurado (E5)."""
        self.tabs.addTab(widget, "💬 Preguntar")
