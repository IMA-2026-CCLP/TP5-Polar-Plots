"""
ui/balloon_view.py — Vista embebida de Plotly con soporte de múltiples modos.
"""
import numpy as np
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import pyqtSignal, QUrl
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFont

from plot.balloon import (
    build_balloon_html,
    build_sphere_html,
    build_polar2d_html,
    build_spectrum_html,
)
from core.symmetry_utils import apply_symmetry

VIEW_MODES = ("3d", "sphere", "polar2d", "spectrum")


class _SilentPage(QWebEnginePage):
    hover_data = pyqtSignal(str)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("HOVER:"):
            self.hover_data.emit(message[6:])


class BalloonView(QWidget):
    """
    Widget que embebe visualizaciones Plotly.

    Modos: '3d' (globo), 'sphere' (esfera), 'polar2d' (polar plano), 'spectrum' (espectro)

    API pública:
        set_data()        — carga arrays y renderiza
        set_band()        — cambia banda activa
        set_colorscale()  — cambia colorscale
        set_view_mode()   — cambia modo de visualización
        set_el_index()    — cambia elevación para polar2d y spectrum
        set_freq_range()  — filtra rango de frecuencias mostrado
        show_placeholder()
    """
    point_hovered = pyqtSignal(str)
    log           = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels:        np.ndarray | None = None
        self._ref_spectrum:  np.ndarray | None = None   # (n_az, n_bands) SPL mic ref
        self._spec_global:   bool = True
        self._azimuths:     np.ndarray | None = None
        self._elevations:   np.ndarray | None = None
        self._bands:        np.ndarray | None = None
        self._band_index:   int   = 0
        self._el_index:     int | None = None
        self._colorscale:   str   = "Plasma"
        self._normalize:    bool  = True
        self._min_db:       float | None = None
        self._max_db:       float | None = None
        self._hz_min:       float | None = None
        self._hz_max:       float | None = None
        self._view_mode:    str   = "3d"
        self._symmetry_type: str  = "none"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._web  = QWebEngineView()
        self._page = _SilentPage(self._web)
        self._page.hover_data.connect(self.point_hovered)
        self._web.setPage(self._page)
        self._web.setStyleSheet("background:#1a1d27;")

        self._placeholder = QLabel(
            "Calculá la directividad\npara ver el patrón polar aquí."
        )
        self._placeholder.setAlignment(
            __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.AlignmentFlag.AlignCenter
        )
        self._placeholder.setStyleSheet("""
            color: #4a5070; font-size: 13pt; background: #1a1d27;
            border: 2px dashed #2a2d3e; border-radius: 16px; padding: 40px;
        """)
        self._placeholder.setFont(QFont("Segoe UI", 12))

        layout.addWidget(self._placeholder)
        layout.addWidget(self._web)
        self._web.hide()

    def _set_html_safe(self, html: str):
        self._web.setHtml(html)

    # ── API pública ───────────────────────────────────────────────────────────

    def set_data(
        self,
        levels:        np.ndarray,
        azimuths:      np.ndarray,
        elevations:    np.ndarray,
        bands:         np.ndarray,
        band_index:    int = 0,
        symmetry_type: str = "none",
        ref_spectrum:  np.ndarray | None = None,
        spec_global:   bool = True,
    ):
        levels_s, azimuths_s, elevations_s = apply_symmetry(
            levels, azimuths, elevations, symmetry_type
        )
        self._levels        = levels_s
        self._ref_spectrum  = ref_spectrum   # (n_az, n_bands)
        self._spec_global   = spec_global
        self._azimuths      = azimuths_s
        self._elevations    = elevations_s
        self._bands         = bands
        self._band_index    = band_index
        self._symmetry_type = symmetry_type
        self._el_index      = None  # reset → auto-detect
        self._render()

    def set_band(self, band_index: int):
        if self._levels is None:
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

    def set_view_mode(self, mode: str):
        if mode not in VIEW_MODES:
            return
        self._view_mode = mode
        if self._levels is not None:
            self._render()

    def set_el_index(self, el_index: int):
        self._el_index = el_index
        if self._levels is not None:
            self._render()

    def set_freq_range(self, hz_min: float | None, hz_max: float | None):
        self._hz_min = hz_min
        self._hz_max = hz_max
        if self._levels is not None:
            self._render()

    def show_placeholder(self):
        self._web.hide()
        self._placeholder.show()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _filtered(self):
        """Devuelve (levels, bands) filtrados por rango de Hz."""
        if self._bands is None:
            return self._levels, self._bands
        mask = np.ones(len(self._bands), dtype=bool)
        if self._hz_min is not None:
            mask &= self._bands >= self._hz_min
        if self._hz_max is not None:
            mask &= self._bands <= self._hz_max
        if not mask.any():
            mask = np.ones(len(self._bands), dtype=bool)
        lvl = self._levels[:, :, mask]
        bnd = self._bands[mask]
        # ajustar band_index si quedó fuera del rango filtrado
        bi = min(self._band_index, lvl.shape[2] - 1)
        return lvl, bnd, bi

    # ── Render ────────────────────────────────────────────────────────────────

    def _render(self):
        if self._levels is None or self._bands is None:
            return

        try:
            self._render_inner()
        except Exception as exc:
            import traceback
            self.log.emit(f"[ERROR] {self._view_mode} render: {exc}\n{traceback.format_exc()}")

    def _render_inner(self):
        lvl, bnd, bi = self._filtered()
        band_hz = float(bnd[bi])

        if self._view_mode == "3d":
            html = build_balloon_html(
                levels=lvl, azimuths=self._azimuths, elevations=self._elevations,
                band_hz=band_hz, band_index=bi,
                colorscale=self._colorscale, normalize=self._normalize,
                min_db=self._min_db, max_db=self._max_db,
            )
        elif self._view_mode == "sphere":
            html = build_sphere_html(
                levels=lvl, azimuths=self._azimuths, elevations=self._elevations,
                band_hz=band_hz, band_index=bi,
                colorscale=self._colorscale,
                min_db=self._min_db, max_db=self._max_db,
            )
        elif self._view_mode == "polar2d":
            html = build_polar2d_html(
                levels=lvl, azimuths=self._azimuths, elevations=self._elevations,
                band_hz=band_hz, band_index=bi,
                el_index=self._el_index,
                colorscale=self._colorscale,
                min_db=self._min_db, max_db=self._max_db,
            )
        elif self._view_mode == "spectrum":
            if self._ref_spectrum is not None:
                html = build_spectrum_html(
                    ref_spl_all = self._ref_spectrum,
                    bands       = bnd,
                    azimuths    = self._azimuths,
                    global_mode = self._spec_global,
                )
            else:
                html = (
                    "<html><body style='background:#1a1d27;color:#4a5070;"
                    "display:flex;align-items:center;justify-content:center;height:100%;'>"
                    "<p>Sin espectro de referencia disponible.</p></body></html>"
                )
        else:
            return

        self._set_html_safe(html)
        self._placeholder.hide()
        self._web.show()
