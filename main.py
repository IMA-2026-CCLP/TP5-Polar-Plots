# -*- coding: utf-8 -*-
"""Punto de entrada de la aplicación Analizador de Directividad Vocal."""

import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox
from PyQt6.QtCore import Qt

from app.config import APP_NAME, APP_VERSION
from app.gui.pantalla_carga import PantallaCarga
from app.gui.pantalla_visualizador import PantallaVisualizador


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1280, 800)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._pantalla_carga = PantallaCarga()
        self._pantalla_viz   = PantallaVisualizador()

        self._stack.addWidget(self._pantalla_carga)   # índice 0
        self._stack.addWidget(self._pantalla_viz)     # índice 1

        self._pantalla_carga.sesion_lista.connect(self._on_sesion_lista)
        self._stack.setCurrentIndex(0)

        self._sesiones_cargadas: set[str] = set()

    def _on_sesion_lista(self, dinamica: str, sesion):
        # Mostrar el visualizador ANTES de cargar la sesión para que
        # el canvas de matplotlib esté visible cuando se dibuje por primera vez
        self._stack.setCurrentIndex(1)
        self._sesiones_cargadas.add(dinamica)
        self._pantalla_viz.agregar_sesion(dinamica, sesion)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    ventana = MainApp()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
