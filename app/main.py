"""
app/main.py — Entry point de Polar Pattern Analyzer.

Correr desde la carpeta app/:
    python main.py

O desde la raíz del proyecto:
    python app/main.py
"""
import sys
import os

# Asegura que app/ esté en el path para imports relativos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
# WebEngine debe importarse antes de crear QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Polar Pattern Analyzer")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("AcousticTools")

    font = QFont()
    font.setFamily("Segoe UI" if sys.platform == "win32" else
                   "SF Pro Display" if sys.platform == "darwin" else "Ubuntu")
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
