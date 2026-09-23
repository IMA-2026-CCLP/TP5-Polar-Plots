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

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt
# WebEngine debe importarse antes de crear QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from version import __version__, APP_NAME
from ui.main_window import MainWindow
from ui.styles import get_qss
from ui import theme as _theme

_ICONS_DIR  = os.path.join(os.path.dirname(__file__), 'ui', 'icons')
_LOGO_SVG   = os.path.join(_ICONS_DIR, 'logo.svg')
_ICON_PATH  = os.path.join(_ICONS_DIR, 'logo.ico')
if not os.path.exists(_ICON_PATH):
    _ICON_PATH = _LOGO_SVG

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


def _make_splash_pixmap(w: int = 460, h: int = 280) -> QPixmap:
    """Logo + nombre + versión sobre un fondo simple, mientras se arma la ventana principal
    (que carga fuentes, docks y las 4 vistas de Directividad y puede tardar un momento)."""
    pal = _theme.LIGHT
    pix = QPixmap(w, h)
    pix.fill(QColor(pal['bg_panel']))

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(pal['border']))
    p.drawRect(0, 0, w - 1, h - 1)

    logo_size = 120
    if os.path.exists(_LOGO_SVG):
        from PyQt6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(_LOGO_SVG)
        if renderer.isValid():
            logo = QPixmap(logo_size, logo_size)
            logo.fill(Qt.GlobalColor.transparent)
            lp = QPainter(logo)
            lp.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(lp)
            lp.end()
            p.drawPixmap((w - logo_size) // 2, 34, logo)

    f_name = QFont(pal['font_display'])
    f_name.setPointSize(15)
    f_name.setBold(True)
    p.setFont(f_name)
    p.setPen(QColor(pal['text']))
    y_name = 34 + logo_size + 30
    p.drawText(0, y_name, w, 24, Qt.AlignmentFlag.AlignHCenter, APP_NAME)

    f_ver = QFont(pal['font_body'])
    f_ver.setPointSize(10)
    p.setFont(f_ver)
    p.setPen(QColor(pal['accent']))
    p.drawText(0, y_name + 26, w, 20, Qt.AlignmentFlag.AlignHCenter, f"v{__version__}")

    f_sub = QFont(pal['font_body'])
    f_sub.setPointSize(9)
    p.setFont(f_sub)
    p.setPen(QColor(pal['text_muted']))
    p.drawText(0, h - 30, w, 20, Qt.AlignmentFlag.AlignHCenter, "Cargando…")

    p.end()
    return pix


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("CCLP")
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))

    splash = QSplashScreen(_make_splash_pixmap())
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    _load_bundled_fonts()
    font = QFont("Segoe UI")
    font.setPointSize(9)
    app.setFont(font)

    # Aplicar en QApplication para que los popups (combos, menús) hereden el tema.
    app.setStyleSheet(get_qss(_theme.current()))

    window = MainWindow()
    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
