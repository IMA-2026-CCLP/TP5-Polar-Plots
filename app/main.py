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
from PyQt6.QtGui import QFont, QFontDatabase, QIcon
# WebEngine debe importarse antes de crear QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from ui.main_window import MainWindow
from ui.styles import get_qss
from ui import theme as _theme

_ICON_PATH = os.path.join(os.path.dirname(__file__), 'ui', 'icons', 'logo.ico')
if not os.path.exists(_ICON_PATH):
    _ICON_PATH = os.path.join(os.path.dirname(__file__), 'ui', 'icons', 'logo.svg')

_FONTS_DIR = os.path.join(os.path.dirname(__file__), 'ui', 'fonts')
_FONT_FILES = [
    'IBMPlexSans-Regular.ttf',
    'IBMPlexSansCondensed-SemiBold.ttf', 'IBMPlexSansCondensed-Bold.ttf',
    'IBMPlexMono-Regular.ttf', 'IBMPlexMono-Medium.ttf', 'IBMPlexMono-SemiBold.ttf',
]


def _load_bundled_fonts():
    for fname in _FONT_FILES:
        path = os.path.join(_FONTS_DIR, fname)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Polar Pattern CCLP")
    app.setApplicationVersion("2.1.0")
    app.setOrganizationName("CCLP")
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))

    _load_bundled_fonts()
    font = QFont("IBM Plex Sans")
    font.setPointSize(10)
    app.setFont(font)

    # Aplicar en QApplication para que los popups (combos, menús) hereden el tema.
    app.setStyleSheet(get_qss(_theme.current()))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
