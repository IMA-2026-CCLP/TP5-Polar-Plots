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
from PyQt6.QtGui import QFont, QIcon
# WebEngine debe importarse antes de crear QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from ui.main_window import MainWindow
from ui.styles import get_qss
from ui.theme import DARK

_ICON_PATH = os.path.join(os.path.dirname(__file__), 'ui', 'icons', 'logo.ico')
if not os.path.exists(_ICON_PATH):
    _ICON_PATH = os.path.join(os.path.dirname(__file__), 'ui', 'icons', 'logo.svg')


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Polar Pattern CCLP")
    app.setApplicationVersion("2.1.0")
    app.setOrganizationName("CCLP")
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))

    font = QFont()
    font.setFamily("Segoe UI" if sys.platform == "win32" else
                   "SF Pro Display" if sys.platform == "darwin" else "Ubuntu")
    font.setPointSize(10)
    app.setFont(font)

    # Aplicar en QApplication para que los popups (combos, menús) hereden el tema.
    app.setStyleSheet(get_qss(DARK))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
