"""Diálogos del Dossier del video: confirmación de costo (proveedor/modelo
propios, independientes del default de Preguntar) y resultado con export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from videoindex.config.settings import MODELOS_POR_PROVEEDOR
from videoindex.infrastructure.llm.providers import PROVEEDORES


class DossierConfirmDialog(QDialog):
    """Selector de proveedor/modelo propio del Dossier (no comparte el
    default de la pestaña Preguntar, a pedido explícito del usuario)."""

    def __init__(self, n_entidades: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar dossier — elegir proveedor")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Se detectaron {n_entidades} entidades en este video."))

        form = QFormLayout()
        self.combo_proveedor = QComboBox()
        self.combo_proveedor.addItems(sorted(PROVEEDORES))
        self.combo_modelo = QComboBox()
        self.combo_modelo.setEditable(True)
        self.combo_proveedor.currentTextChanged.connect(self._modelos_del_proveedor)
        self._modelos_del_proveedor(self.combo_proveedor.currentText())
        form.addRow("Proveedor:", self.combo_proveedor)
        form.addRow("Modelo:", self.combo_modelo)
        layout.addLayout(form)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def _modelos_del_proveedor(self, proveedor: str):
        self.combo_modelo.clear()
        if proveedor == "lmstudio":
            from videoindex.infrastructure.llm.providers import modelos_cargados_lmstudio

            modelos = modelos_cargados_lmstudio()
            if not modelos:
                self.combo_modelo.setPlaceholderText("LM Studio no responde (¿servidor iniciado?)")
            self.combo_modelo.addItems(modelos)
            return
        if proveedor == "ollama":
            from videoindex.infrastructure.llm.providers import modelos_instalados_ollama

            modelos = modelos_instalados_ollama()
            if not modelos:
                self.combo_modelo.setPlaceholderText("Ollama no responde (¿servidor iniciado?)")
            self.combo_modelo.addItems(modelos)
            return
        self.combo_modelo.addItems(MODELOS_POR_PROVEEDOR.get(proveedor, []))

    def proveedor_modelo(self) -> tuple[str, str]:
        proveedor = self.combo_proveedor.currentText()
        modelo = self.combo_modelo.currentText().strip() or PROVEEDORES[proveedor][1]
        return proveedor, modelo


class DossierResultDialog(QDialog):
    def __init__(self, video_title: str, markdown: str, costo_resumen: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Dossier — {video_title}")
        self.resize(700, 600)
        self._markdown = markdown

        layout = QVBoxLayout(self)
        visor = QTextBrowser()
        visor.setMarkdown(markdown)
        layout.addWidget(visor, stretch=1)
        layout.addWidget(QLabel(costo_resumen))

        boton_exportar = QPushButton("💾 Exportar a Markdown…")
        boton_exportar.clicked.connect(self._exportar)
        layout.addWidget(boton_exportar)

        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(self.reject)
        cerrar.accepted.connect(self.accept)
        layout.addWidget(cerrar)

    def _exportar(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar dossier", "", "Markdown (*.md)")
        if not ruta:
            return
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(self._markdown, encoding="utf-8")
        QMessageBox.information(self, "Exportado", f"Dossier guardado en:\n{destino}")
