"""
ui/spectrum_view.py — Vista Espectro nativa con pyqtgraph (reemplaza el
render Plotly/QWebEngineView). Barras 1/3 de octava del micrófono de
referencia, modo Global (media ± σ) o Por toma (una serie por azimuth).

API pública idéntica a la porción de BalloonView que usa TabDirectividad,
ver ui/polar2d_view.py para la misma nota de contrato.
"""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.data_store import freq_label
from plot.balloon import FONT_SIZE

pg.setConfigOptions(antialias=True)


def _az_colors_rgb(n: int) -> list:
    """n colores tipo arco iris como tuplas (r,g,b) — pg.mkBrush no
    interpreta el formato 'rgb(r,g,b)' de CSS que usa plot.balloon._az_colors
    (pensado para incrustar en HTML), así que se genera aparte en vez de
    reusar esa función."""
    import colorsys
    return [
        tuple(int(c * 255) for c in colorsys.hsv_to_rgb(i / n, 0.75, 0.95))
        for i in range(n)
    ]


class SpectrumView(QWidget):
    """Reemplazo nativo de BalloonView para el modo 'spectrum'."""

    point_hovered           = pyqtSignal(str)
    log                     = pyqtSignal(str)
    context_menu_requested  = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ref_spectrum = None
        self._bands = None
        self._azimuths = None
        self._spec_global = True
        self._show_info = True
        self._style = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._placeholder = QLabel("Calculá la directividad\npara ver el espectro aquí.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("background:#ffffff; color:#7a7a7a; font-size:11pt; border:none;")

        self._plot = pg.PlotWidget()
        self._plot.setBackground('#ffffff')   # fondo fijo, ver tab_directividad.py
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setLabel('left', 'dB SPL', color='#000000', **{'font-size': f'{FONT_SIZE}px'})
        self._plot.setLabel('bottom', 'Frecuencia [Hz]', color='#000000', **{'font-size': f'{FONT_SIZE}px'})
        tick_font = QFont("Segoe UI")
        tick_font.setPixelSize(FONT_SIZE)
        for ax in ('left', 'bottom'):          # ejes negros sobre el fondo blanco fijo
            axis = self._plot.getAxis(ax)
            axis.setPen('#000000')
            axis.setTextPen('#000000')
            axis.setStyle(tickFont=tick_font)
        self._plot.getPlotItem().setMenuEnabled(False)
        self._legend = None

        self._info_label = QLabel(self._plot)
        self._info_label.setStyleSheet(
            "background: rgba(255,255,255,.9); color: #000000; "
            "border-radius: 6px; padding: 6px 10px; font-size: 9pt;"
        )
        self._info_label.move(8, 8)
        self._info_label.hide()

        layout.addWidget(self._placeholder)
        layout.addWidget(self._plot)
        self._plot.hide()
        self._plot.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.ContextMenu:
            pos = event.pos()
            self.context_menu_requested.emit(pos.x(), pos.y())
            return True
        return super().eventFilter(obj, event)

    def mapToGlobal(self, pos):
        return self._plot.mapToGlobal(pos)

    # ── API pública (no-ops donde no aplica, ver contrato en polar2d_view.py) ──

    def set_data(self, levels, azimuths, elevations, bands, band_index=0,
                 symmetry_type="none", ref_spectrum=None, spec_global=True):
        self._bands = bands
        self._azimuths = azimuths
        self._ref_spectrum = ref_spectrum
        self._spec_global = spec_global
        self._render()

    def set_view_mode(self, mode): pass

    def set_unit(self, unit: str):
        """'dB SPL' (calibrado) o 'dBFS' (sin calibrar)."""
        self._plot.setLabel('left', unit, color='#000000', **{'font-size': f'{FONT_SIZE}px'})
    def set_band(self, band_index): pass
    def set_colorscale(self, name): pass
    def set_normalize(self, value): pass
    def set_db_range(self, min_db, max_db): pass
    def set_el_index(self, el_index): pass
    def set_compare_bands(self, indices): pass
    def set_compare_styles(self, styles): pass
    def set_tick_font_size(self, size): pass
    def set_axis_style(self, color, width): pass
    def set_plane(self, plane): pass
    def set_freq_range(self, hz_min, hz_max): pass
    def set_camera_view(self, view): pass
    def apply_theme(self, palette: dict): pass   # fondo blanco fijo

    def set_style(self, style):
        self._style = style or {}
        if self._ref_spectrum is not None:
            self._render()

    def set_show_info(self, show):
        self._show_info = show
        self._info_label.setVisible(show and self._ref_spectrum is not None)

    def show_placeholder(self):
        self._plot.hide()
        self._placeholder.show()

    def export_image(self, path: str, dpi: int = 300, fmt: str = 'png', on_done=None):
        import pyqtgraph.exporters as pg_exporters
        from ui.export_utils import EXPORT_BASE_W, set_png_dpi
        try:
            if fmt == 'svg':
                from ui.export_utils import export_pg_svg
                export_pg_svg(self._plot, path, dpi)
                if on_done:
                    on_done(True)
                return
            else:
                exporter = pg_exporters.ImageExporter(self._plot.getPlotItem())
                # re-renderiza la escena (vectorial) a este ancho: nítido, no es una captura
                exporter.parameters()['width'] = int(round(EXPORT_BASE_W * dpi / 96))
            exporter.export(path)
            if fmt != 'svg':
                set_png_dpi(path, dpi)
            if on_done:
                on_done(True)
        except Exception as e:
            self.log.emit(f"[ERROR] Exportando Espectro: {e}")
            if on_done:
                on_done(False)

    # ── Render ───────────────────────────────────────────────────────────

    def _render(self):
        if self._ref_spectrum is None or self._bands is None:
            self.show_placeholder()
            return
        self._plot.show()
        self._placeholder.hide()
        self._plot.clear()
        if self._legend is not None:
            self._legend.scene().removeItem(self._legend)
            self._legend = None

        sort_idx = np.argsort(self._bands)
        bands = self._bands[sort_idx]
        ref = self._ref_spectrum[:, sort_idx]
        x_labels = [freq_label(float(b)) for b in bands]
        n_bands = len(bands)
        x = np.arange(n_bands)

        bar_color = self._style.get('bar_color') or '#146B64'

        if self._spec_global:
            mean_vals = np.nanmean(ref, axis=0)
            std_vals  = np.nanstd(ref, axis=0, ddof=0)
            bars = pg.BarGraphItem(x=x, height=mean_vals, width=0.6,
                                    brush=pg.mkBrush(bar_color), pen=pg.mkPen('#1B1F24', width=0.5))
            self._plot.addItem(bars)
            err = pg.ErrorBarItem(x=x, y=mean_vals, height=std_vals * 2,
                                   pen=pg.mkPen('#C4791F', width=2))
            self._plot.addItem(err)
            fin = mean_vals[np.isfinite(mean_vals)]
            std_fin = std_vals[np.isfinite(std_vals)]
            y_min = float((fin - std_fin).min()) - 2 if len(fin) else -80
            y_max = float((fin + std_fin).max()) + 2 if len(fin) else 0
            desc = f"Global — {len(self._azimuths)} azimuths · media ± σ"
        else:
            n_az = len(self._azimuths)
            colors = _az_colors_rgb(n_az)
            group_w = 0.8
            bar_w = group_w / max(n_az, 1)
            for i, az in enumerate(self._azimuths):
                offset = (i - n_az / 2) * bar_w
                r, g, b = colors[i]
                bars = pg.BarGraphItem(
                    x=x + offset, height=np.nan_to_num(ref[i], nan=0.0), width=bar_w,
                    brush=pg.mkBrush(r, g, b, 140),
                    name=f"{float(az):.0f}°",
                )
                self._plot.addItem(bars)
            all_v = ref[np.isfinite(ref)]
            y_min = float(all_v.min()) - 1 if len(all_v) else -80
            y_max = float(all_v.max()) + 1 if len(all_v) else 0
            desc = f"0°–180° — {n_az} azimuths superpuestos"

        axis = self._plot.getAxis('bottom')
        axis.setTicks([[(i, lbl) for i, lbl in enumerate(x_labels)]])
        self._plot.setYRange(y_min, y_max, padding=0)
        self._plot.setXRange(-0.6, n_bands - 0.4, padding=0)

        range_str = f"{freq_label(float(bands[0]))}–{freq_label(float(bands[-1]))} Hz"
        self._info_label.setText(f"Mic ref — {desc}\nBandas: {range_str}")
        self._info_label.adjustSize()
        self._info_label.setVisible(self._show_info)
