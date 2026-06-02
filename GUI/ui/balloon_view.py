"""
ui/balloon_view.py — QWebEngineView wrapper para el balloon 3D
"""
import numpy as np
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import pyqtSignal, QUrl
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFont

from plot.balloon import build_balloon_html
from core.symmetry_utils import apply_symmetry


class _SilentPage(QWebEnginePage):
    """Página que intercepta console.log para bridge JS→Python."""

    hover_data = pyqtSignal(str)   # JSON string del punto hovereado

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("HOVER:"):
            self.hover_data.emit(message[6:])
        # silencia el resto (no llenar stdout de ruido Plotly)


class BalloonView(QWidget):
    """
    Widget que embebe el balloon de Plotly.
    Métodos clave:
        set_data()     — carga arrays y refresca
        set_band()     — cambia de banda sin recargar los datos
        set_colorscale — cambia colorscale
    """

    # Emitido cuando JS reporta un punto hover
    point_hovered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels:     np.ndarray | None = None
        self._azimuths:   np.ndarray | None = None
        self._elevations: np.ndarray | None = None
        self._bands:      np.ndarray | None = None
        self._band_index: int = 0
        self._colorscale: str = "Plasma"
        self._normalize:  bool = True
        self._min_db:     float | None = None
        self._max_db:     float | None = None
        self._symmetry_type: str = 'none'

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._web = QWebEngineView()
        self._page = _SilentPage(self._web)
        self._page.hover_data.connect(self.point_hovered)
        self._web.setPage(self._page)

        # Fondo oscuro mientras carga
        self._web.setStyleSheet("background:#1a1d27;")

        self._placeholder = QLabel("Cargá una carpeta y procesá los audios\npara ver el patrón polar 3D aquí.")
        self._placeholder.setAlignment(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("""
            color: #4a5070;
            font-size: 13pt;
            background: #1a1d27;
            border: 2px dashed #2a2d3e;
            border-radius: 16px;
            padding: 40px;
        """)
        self._placeholder.setFont(QFont("Inter", 12))

        layout.addWidget(self._placeholder)
        layout.addWidget(self._web)
        self._web.hide()

    # ── API pública ───────────────────────────────────────────────────────

    def set_data(
        self,
        levels:     np.ndarray,
        azimuths:   np.ndarray,
        elevations: np.ndarray,
        bands:      np.ndarray,
        band_index: int = 0,
        symmetry_type: str = 'none',
    ):
        # Aplicar simetrías si es necesario
        levels_sym, azimuths_sym, elevations_sym = apply_symmetry(
            levels, azimuths, elevations, symmetry_type
        )
        
        self._levels     = levels_sym
        self._azimuths   = azimuths_sym
        self._elevations = elevations_sym
        self._bands      = bands
        self._band_index = band_index
        self._symmetry_type = symmetry_type
        self._render()

    def set_band(self, band_index: int):
        if self._levels is None:
            print("ERR: No levels data yet, cannot change band.")
            return
        self._band_index = band_index
        self._render()

    def set_colorscale(self, name: str):
        self._colorscale = name
        if self._levels is not None:
            self._render()

    def set_normalize(self, value: bool):
        self._normalize = value
        if self._levels is not None:
            self._render()

    def set_db_range(self, min_db: float | None, max_db: float | None):
        self._min_db = min_db
        self._max_db = max_db
        if self._levels is not None:
            self._render()

    def show_placeholder(self):
        self._web.hide()
        self._placeholder.show()

    # ── Render ────────────────────────────────────────────────────────────

    def _render(self):
        if self._levels is None or self._bands is None:
            print("ERR: No levels or bands data yet.")
            return

        band_hz = float(self._bands[self._band_index])

        html = build_balloon_html(
            levels     = self._levels,
            azimuths   = self._azimuths,
            elevations = self._elevations,
            band_hz    = band_hz,
            band_index = self._band_index,
            colorscale = self._colorscale,
            normalize  = self._normalize,
            min_db     = self._min_db,
            max_db     = self._max_db,
        )

        self._web.setHtml(html, QUrl("about:blank"))
        self._placeholder.hide()
        self._web.show()
