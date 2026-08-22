"""
ui/polar2d_view.py — Vista Polar 2D nativa con pyqtgraph (reemplaza el
render Plotly/QWebEngineView, mismo enfoque que ui/f0_editor.py y
ui/waveform_editor.py). La preparación de datos (suavizado circular,
interpolación, normalización a 0 dB) vive en plot/balloon.py
(compute_polar2d_ring) y se reutiliza tal cual — acá sólo cambia cómo se
dibuja.

API pública idéntica a la porción de BalloonView que usa TabDirectividad
(ver ui/balloon_view.py) para que _ViewSection no tenga que saber qué
backend de render está usando.
"""
import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QToolTip

from core.symmetry_utils import apply_symmetry
from plot.balloon import compute_polar2d_ring, _COMPARE_COLORS

pg.setConfigOptions(antialias=True)

_DASH_QT = {
    "solid":   Qt.PenStyle.SolidLine,
    "dash":    Qt.PenStyle.DashLine,
    "dot":     Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
    "longdash": Qt.PenStyle.DashLine,
}


class Polar2DView(QWidget):
    """Reemplazo nativo de BalloonView para el modo 'polar2d'."""

    point_hovered           = pyqtSignal(str)
    log                     = pyqtSignal(str)
    context_menu_requested  = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels = None
        self._azimuths = None
        self._elevations = None
        self._bands = None
        self._band_index = 0
        self._el_index = None
        self._plane = "XY"
        self._show_info = True
        self._compare_bands = None
        self._compare_styles = {}
        self._tick_font_size = 11
        self._style = {}
        self._min_db = None
        self._max_db = None
        self._symmetry_type = "none"
        self._rings_last = []   # último cómputo, para hover/export

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._placeholder = QLabel("Calculá la directividad\npara ver el patrón polar aquí.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setFont(QFont("IBM Plex Sans", 12))

        self._plot = pg.PlotWidget()
        self._plot.setBackground('#ffffff')   # fondo fijo, ver tab_directividad.py
        self._vb = self._plot.getPlotItem().getViewBox()
        self._vb.setAspectLocked(True)
        self._plot.hideAxis('bottom')
        self._plot.hideAxis('left')
        self._plot.getPlotItem().setMenuEnabled(False)
        self._legend = None

        self._info_label = QLabel(self._plot)
        self._info_label.setStyleSheet(
            "background: rgba(255,255,255,.9); color: #1a1a1a; "
            "border-radius: 6px; padding: 6px 10px; font-size: 9pt;"
        )
        self._info_label.move(8, 8)
        self._info_label.hide()

        layout.addWidget(self._placeholder)
        layout.addWidget(self._plot)
        self._plot.hide()

        self._proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved)
        self._plot.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.ContextMenu:
            pos = event.pos()
            self.context_menu_requested.emit(pos.x(), pos.y())
            return True
        return super().eventFilter(obj, event)

    def mapToGlobal(self, pos):
        return self._plot.mapToGlobal(pos)

    # ── API pública ──────────────────────────────────────────────────────

    def set_data(self, levels, azimuths, elevations, bands, band_index=0,
                 symmetry_type="none", ref_spectrum=None, spec_global=True):
        levels_s, azimuths_s, elevations_s = apply_symmetry(levels, azimuths, elevations, symmetry_type)
        self._levels = levels_s
        self._azimuths = azimuths_s
        self._elevations = elevations_s
        self._bands = bands
        self._band_index = band_index
        self._symmetry_type = symmetry_type
        self._el_index = None
        self._render()

    def set_view_mode(self, mode):
        pass   # esta vista sólo sirve 'polar2d', no hay otro modo que aceptar

    def set_band(self, band_index):
        self._band_index = band_index
        if self._levels is not None:
            self._render()

    def set_colorscale(self, name):
        pass   # no aplica a Polar 2D

    def set_normalize(self, value):
        pass   # no aplica a Polar 2D

    def set_db_range(self, min_db, max_db):
        self._min_db = min_db
        self._max_db = max_db
        if self._levels is not None:
            self._render()

    def set_el_index(self, el_index):
        self._el_index = el_index
        if self._levels is not None:
            self._render()

    def set_compare_bands(self, indices):
        self._compare_bands = indices if indices and len(indices) > 1 else None
        if self._levels is not None:
            self._render()

    def set_compare_styles(self, styles):
        self._compare_styles = styles or {}
        if self._levels is not None:
            self._render()

    def set_tick_font_size(self, size):
        self._tick_font_size = size
        if self._levels is not None:
            self._render()

    def set_axis_style(self, color, width):
        pass   # sólo aplica a 3d/sphere

    def set_style(self, style):
        self._style = style or {}
        if self._levels is not None:
            self._render()

    def set_plane(self, plane):
        self._plane = plane
        if self._levels is not None:
            self._render()

    def set_show_info(self, show):
        self._show_info = show
        self._info_label.setVisible(show and bool(self._rings_last))

    def set_freq_range(self, hz_min, hz_max):
        pass   # el filtrado de rango lo aplica TabDirectividad sobre band_selector

    def set_camera_view(self, view):
        pass   # sólo aplica a 3d/sphere

    def show_placeholder(self):
        self._plot.hide()
        self._placeholder.show()

    def apply_theme(self, palette: dict):
        pass   # el fondo del gráfico queda blanco fijo, ver tab_directividad.py

    def export_image(self, path: str, dpi: int = 300, fmt: str = 'png', on_done=None):
        import pyqtgraph.exporters as pg_exporters
        try:
            if fmt == 'svg':
                exporter = pg_exporters.SVGExporter(self._plot.getPlotItem())
            else:
                exporter = pg_exporters.ImageExporter(self._plot.getPlotItem())
                scale = max(1, round(dpi / 96))
                exporter.parameters()['width'] = int(self._plot.width() * scale)
            exporter.export(path)
            if on_done:
                on_done(True, path)
        except Exception as e:
            self.log.emit(f"[ERROR] Exportando Polar 2D: {e}")
            if on_done:
                on_done(False, str(e))

    # ── Render ───────────────────────────────────────────────────────────

    def _render(self):
        if self._levels is None:
            self.show_placeholder()
            return
        self._plot.show()
        self._placeholder.hide()

        bands_to_plot = (
            [(i, float(self._bands[i])) for i in self._compare_bands]
            if self._compare_bands else
            [(self._band_index, float(self._bands[self._band_index]))]
        )
        multi = len(bands_to_plot) > 1

        rings = [
            compute_polar2d_ring(
                self._levels[:, :, bi], bi, bhz, self._azimuths, self._elevations,
                self._plane, self._el_index, self._style,
            )
            for bi, bhz in bands_to_plot
        ]
        self._rings_last = rings

        step = self._style.get('ring_step', 5.0)
        all_min = min(r['gmin'] for r in rings)
        all_max = max(r['gmax'] for r in rings)
        r_floor = self._min_db if self._min_db is not None else math.floor(all_min / step) * step
        r_ceil  = self._max_db if self._max_db is not None else (
            math.ceil(all_max / step) * step if multi else 0.0)
        if r_ceil <= r_floor:
            r_ceil = r_floor + step
        dyn_range = r_ceil - r_floor

        def db_to_r(db):
            return np.clip((np.asarray(db, float) - r_floor) / dyn_range, 0, 1)

        rotation = 90.0 if self._plane == "XY" else 0.0

        def to_xy(theta_deg, r):
            ang = np.radians(rotation + np.asarray(theta_deg, float))
            return r * np.cos(ang), r * np.sin(ang)

        self._plot.clear()
        if self._legend is not None:
            self._legend.scene().removeItem(self._legend)
            self._legend = None

        ring_color = self._style.get('ring_color') or '#000000'
        ring_font  = self._style.get('ring_font_size', 9)
        ring_vals  = np.arange(math.ceil(r_floor / step) * step, r_ceil + 0.01, step)
        ring_vals  = ring_vals[(ring_vals > r_floor) & (ring_vals <= r_ceil)]
        theta_ring = np.linspace(0, 360, 181)
        for db in ring_vals:
            r_ring = float(db_to_r(db))
            rx, ry = to_xy(theta_ring, r_ring)
            circle = pg.PlotCurveItem(rx, ry, pen=pg.mkPen(ring_color, width=1, style=Qt.PenStyle.DotLine))
            self._plot.addItem(circle)
            label_ang = self._style.get('ring_label_angle', 92)
            lx, ly = to_xy(label_ang, r_ring)
            txt = pg.TextItem(f"{db:g}", color=self._style.get('text_color') or '#5B6570', anchor=(0.5, 0.5))
            txt.setFont(QFont("IBM Plex Mono", int(ring_font)))
            txt.setPos(lx, ly)
            self._plot.addItem(txt)

        for a in range(0, 360, 30):
            ax, ay = to_xy(a, 1.06)
            txt = pg.TextItem(f"{a}°", color='#1B1F24', anchor=(0.5, 0.5))
            txt.setFont(QFont("IBM Plex Mono", int(self._tick_font_size)))
            txt.setPos(ax, ay)
            self._plot.addItem(txt)
            sx, sy = to_xy(a, 1.0)
            spoke = pg.PlotCurveItem([0, sx], [0, sy], pen=pg.mkPen(ring_color, width=1, style=Qt.PenStyle.DotLine))
            self._plot.addItem(spoke)

        if multi:
            self._legend = self._plot.addLegend(offset=(-10, 10))

        default_width = self._style.get('line_width', 2.5)
        for i, ring in enumerate(rings):
            band_style = self._compare_styles.get(ring['band_index'], {})
            color = band_style.get('color', _COMPARE_COLORS[i % len(_COMPARE_COLORS)])
            width = band_style.get('width', default_width)
            dash  = _DASH_QT.get(band_style.get('dash', 'solid'), Qt.PenStyle.SolidLine)
            r_plot = db_to_r(ring['r_closed'])
            x, y = to_xy(ring['az_closed'], r_plot)
            name = f"{ring['band_hz']:.0f} Hz" if multi else None
            curve = pg.PlotDataItem(x, y, pen=pg.mkPen(color, width=width, style=dash), name=name)
            self._plot.addItem(curve)

        self._vb.setRange(xRange=(-1.15, 1.15), yRange=(-1.15, 1.15), padding=0)

        r0 = rings[0]
        if multi:
            bands_str = ", ".join(f"{r['band_hz']:.0f}" for r in rings)
            info = (f"Comparando {len(rings)} bandas: {bands_str} Hz\n{r0['title_extra']}\n"
                    f"Dinámica combinada: {r_ceil - r_floor:.1f} dB")
        else:
            info = (f"Banda: {r0['band_hz']:.0f} Hz\n{r0['title_extra']}\n"
                    f"Máx: {r0['gmax']:.1f} dB  ·  Dinámica: {r0['gmax'] - r0['gmin']:.1f} dB")
        self._info_label.setText(info)
        self._info_label.adjustSize()
        self._info_label.setVisible(self._show_info)

        self._db_to_r_params = (r_floor, dyn_range, rotation)

    # ── Hover ────────────────────────────────────────────────────────────

    def _on_mouse_moved(self, evt):
        if not self._rings_last:
            QToolTip.hideText()
            return
        pos = evt[0]
        if not self._plot.sceneBoundingRect().contains(pos):
            QToolTip.hideText()
            return
        pt = self._vb.mapSceneToView(pos)
        r_floor, dyn_range, rotation = getattr(self, '_db_to_r_params', (0, 1, 90))
        r = math.hypot(pt.x(), pt.y())
        if r > 1.15:
            QToolTip.hideText()
            return
        ang = (math.degrees(math.atan2(pt.y(), pt.x())) - rotation) % 360
        ring = self._rings_last[0]
        idx = int(np.argmin(np.abs(ring['az_closed'] - ang)))
        db_val = ring['r_abs_cl'][idx]
        label = ring['hover_label']
        QToolTip.showText(QCursor.pos(), f"{label}: {ring['az_closed'][idx]:.0f}°\n{db_val:.1f} dB SPL")
        self.point_hovered.emit(f"{label}={ring['az_closed'][idx]:.0f} dB={db_val:.1f}")
