"""
ui/balloon_view.py — Vista embebida de Plotly con soporte de múltiples modos.
"""
import json
import numpy as np
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import pyqtSignal, QUrl, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFont

from plot.balloon import (
    build_balloon_html,
    build_sphere_html,
    build_polar2d_html,
    build_spectrum_html,
)
from core.symmetry_utils import apply_symmetry

# Presets de cámara para las vistas 3D/Esfera. Convención de ejes de la app
# (ver plot/balloon.py _axes_traces): X = frente (0°), Y = 90°, Z = cénit.
_CAMERA_PRESETS = {
    "top":    {"eye": {"x": 0.0001, "y": 0.0001, "z": 2.5},  "up": {"x": 0, "y": 1, "z": 0}},
    "bottom": {"eye": {"x": 0.0001, "y": 0.0001, "z": -2.5}, "up": {"x": 0, "y": 1, "z": 0}},
    "front":  {"eye": {"x": 2.5, "y": 0.0001, "z": 0.0001},  "up": {"x": 0, "y": 0, "z": 1}},
    "back":   {"eye": {"x": -2.5, "y": 0.0001, "z": 0.0001}, "up": {"x": 0, "y": 0, "z": 1}},
}

VIEW_MODES = ("3d", "sphere", "polar2d", "spectrum")


class _SilentPage(QWebEnginePage):
    hover_data          = pyqtSignal(str)
    context_menu_at     = pyqtSignal(int, int)   # x, y en píxeles locales de la página

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("HOVER:"):
            self.hover_data.emit(message[6:])
        elif message.startswith("CONTEXTMENU:"):
            try:
                x_str, y_str = message[len("CONTEXTMENU:"):].split(',')
                self.context_menu_at.emit(int(float(x_str)), int(float(y_str)))
            except (ValueError, IndexError):
                pass


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
    point_hovered       = pyqtSignal(str)
    log                 = pyqtSignal(str)
    context_menu_requested = pyqtSignal(int, int)   # x, y en píxeles locales del widget

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
        self._plane:        str   = "XY"
        self._show_info:    bool  = True
        self._compare_bands: list | None = None   # índices de banda a superponer (polar2d)
        self._compare_styles: dict = {}           # {band_index: {'color','width','dash'}}
        self._tick_font_size: float = 11          # tamaño de números de los ejes (polar2d)
        self._axis_color:    str | None = None    # color de la grilla 3D (3d/sphere), None = tema
        self._axis_width:    float = 1            # grosor de la grilla 3D
        self._colorscale:   str   = "Plasma"
        self._normalize:    bool  = True
        self._min_db:       float | None = None
        self._max_db:       float | None = None
        self._hz_min:       float | None = None
        self._hz_max:       float | None = None
        self._view_mode:    str   = "3d"
        self._symmetry_type: str  = "none"
        # True una vez que la página cargó por primera vez y expone
        # window.updatePlot — hasta entonces cada render hace un setHtml()
        # completo; después, los renders usan Plotly.react() in-place para
        # no perder cámara/zoom/paneo (ver plot/balloon.py _wrap_html).
        self._html_loaded: bool = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._web  = QWebEngineView()
        self._page = _SilentPage(self._web)
        self._page.hover_data.connect(self.point_hovered)
        self._page.context_menu_at.connect(self.context_menu_requested)
        self._web.setPage(self._page)
        self._web.loadFinished.connect(self._on_load_finished)

        self._placeholder = QLabel(
            "Calculá la directividad\npara ver el patrón polar aquí."
        )
        self._placeholder.setAlignment(
            __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.AlignmentFlag.AlignCenter
        )

        from ui import theme as _t
        self._apply_theme_styles(_t.current())
        self._placeholder.setFont(QFont("Segoe UI", 12))

        layout.addWidget(self._placeholder)
        layout.addWidget(self._web)
        self._web.hide()

    def _apply_theme_styles(self, palette: dict):
        bg = palette['plot_bg']
        self._web.setStyleSheet(f"background:{bg};")
        self._placeholder.setStyleSheet(
            f"color: {palette['text_muted']}; font-size: 13pt; background: {bg};"
            f" border: 2px dashed {palette['border']}; border-radius: 16px; padding: 40px;"
        )

    def _set_html_safe(self, html: str):
        self._html_loaded = False
        self._web.setHtml(html)

    def _on_load_finished(self, ok: bool):
        self._html_loaded = ok

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

    def set_compare_bands(self, indices: list | None):
        """Índices (dentro de self._bands) de las bandas a superponer en polar2d.
        None o <2 índices desactiva el modo comparación."""
        self._compare_bands = indices if indices and len(indices) > 1 else None
        if self._levels is not None:
            self._render()

    def set_compare_styles(self, styles: dict):
        """{band_index: {'color','width','dash'}} — overrides de estilo por
        banda en el modo comparación de polar2d (ver diálogo "Propiedades
        de bandas…")."""
        self._compare_styles = styles or {}
        if self._levels is not None:
            self._render()

    def set_tick_font_size(self, size: float):
        """Tamaño de los números del eje angular (y de las etiquetas de
        dB de los anillos, en proporción) del gráfico polar2d."""
        self._tick_font_size = size
        if self._levels is not None:
            self._render()

    def set_axis_style(self, color: str | None, width: float):
        """Color y grosor de la grilla/ejes de las escenas 3D (3d/sphere).
        color=None restaura el color del tema."""
        self._axis_color = color
        self._axis_width = width
        if self._levels is not None:
            self._render()

    def set_plane(self, plane: str):
        self._plane = plane
        if self._levels is not None:
            self._render()

    def set_show_info(self, show: bool):
        self._show_info = show
        if self._levels is not None:
            self._render()

    def set_freq_range(self, hz_min: float | None, hz_max: float | None):
        self._hz_min = hz_min
        self._hz_max = hz_max
        if self._levels is not None:
            self._render()

    def set_camera_view(self, view: str):
        """
        Posiciona la cámara de la escena 3D en un preset (top/bottom/front/back),
        vía Plotly.relayout sobre el plot ya cargado (sin re-renderizar los datos).
        Sólo aplica a los modos '3d' y 'sphere'.
        """
        preset = _CAMERA_PRESETS.get(view)
        if preset is None or self._view_mode not in ("3d", "sphere"):
            return
        js = (
            "Plotly.relayout(document.getElementById('plot'), "
            f"{{'scene.camera': {json.dumps(preset)}}})"
        )
        self._web.page().runJavaScript(js)

    def show_placeholder(self):
        self._web.hide()
        self._placeholder.show()

    def export_image(self, path: str, on_done=None):
        """
        Exporta el gráfico ocultando primero la barra flotante de iconos de
        Plotly (cámara, zoom, selección, comentario) vía CSS, capturando el
        widget con QWebEngineView.grab() (síncrono, nativo de Qt) y
        restaurando la barra después.

        Se usa grab() en vez de Plotly.toImage(): éste depende de que la
        promesa de JS sea correctamente esperada entre el proceso de Qt y
        el motor de renderizado, lo cual resultó poco confiable (fallaba
        silenciosamente). grab() no tiene esa dependencia.

        on_done, si se pasa, se llama con (ok: bool) al terminar — permite
        encadenar exportaciones en lote sin pisarse (ver export_all_images
        en TabDirectividad).
        """
        hide_js = "var m=document.querySelector('.modebar'); if(m) m.style.visibility='hidden';"
        show_js = "var m=document.querySelector('.modebar'); if(m) m.style.visibility='';"

        def _do_grab():
            pixmap = self._web.grab()
            self._web.page().runJavaScript(show_js)
            ok = pixmap.save(path)
            if ok:
                self.log.emit(f"[Dir] Imagen guardada → {path}")
            else:
                self.log.emit(f"[ERROR] No se pudo guardar la imagen en {path}")
            if on_done:
                on_done(ok)

        def _after_hide(_result=None):
            # Pequeño margen para que Chromium repinte tras ocultar la barra
            # antes de que Qt capture el frame actual del widget.
            QTimer.singleShot(50, _do_grab)

        self._web.page().runJavaScript(hide_js, _after_hide)

    def apply_theme(self, palette: dict):
        """Aplica la nueva paleta y re-renderiza el plot activo."""
        self._apply_theme_styles(palette)
        if self._levels is not None:
            self._render()

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
        # Una vez cargada la página por primera vez, los renders siguientes
        # actualizan in-place (Plotly.react) para conservar cámara/zoom/paneo,
        # en vez de recargar todo con setHtml() (ver plot/balloon.py _wrap_html).
        use_update = self._html_loaded

        if self._view_mode == "3d":
            html = build_balloon_html(
                levels=lvl, azimuths=self._azimuths, elevations=self._elevations,
                band_hz=band_hz, band_index=bi,
                colorscale=self._colorscale, normalize=self._normalize,
                min_db=self._min_db, max_db=self._max_db,
                show_info=self._show_info,
                axis_color=self._axis_color, axis_width=self._axis_width,
                update_only=use_update,
            )
        elif self._view_mode == "sphere":
            html = build_sphere_html(
                levels=lvl, azimuths=self._azimuths, elevations=self._elevations,
                band_hz=band_hz, band_index=bi,
                colorscale=self._colorscale,
                min_db=self._min_db, max_db=self._max_db,
                show_info=self._show_info,
                axis_color=self._axis_color, axis_width=self._axis_width,
                update_only=use_update,
            )
        elif self._view_mode == "polar2d":
            compare_bands = None
            if self._compare_bands:
                # Índices tomados de self._bands (ver set_compare_bands): válidos
                # contra 'lvl' porque _filtered() no recorta bandas salvo que se
                # use set_freq_range(), que hoy no se invoca desde ningún lado.
                compare_bands = [(i, float(self._bands[i])) for i in self._compare_bands]
            html = build_polar2d_html(
                levels=lvl, azimuths=self._azimuths, elevations=self._elevations,
                band_hz=band_hz, band_index=bi,
                el_index=self._el_index,
                plane=self._plane,
                colorscale=self._colorscale,
                min_db=self._min_db, max_db=self._max_db,
                show_info=self._show_info,
                compare_bands=compare_bands,
                compare_styles=self._compare_styles,
                tick_font_size=self._tick_font_size,
                update_only=use_update,
            )
        elif self._view_mode == "spectrum":
            if self._ref_spectrum is not None:
                html = build_spectrum_html(
                    ref_spl_all = self._ref_spectrum,
                    bands       = bnd,
                    azimuths    = self._azimuths,
                    global_mode = self._spec_global,
                    show_info   = self._show_info,
                    update_only = use_update,
                )
            else:
                from ui import theme as _t
                _p = _t.current()
                html = (
                    f"<html><body style='background:{_p['plot_bg']};color:{_p['text_muted']};"
                    "display:flex;align-items:center;justify-content:center;height:100%;'>"
                    "<p>Sin espectro de referencia disponible.</p></body></html>"
                )
                use_update = False   # documento estático, no soporta update in-place
        else:
            return

        if use_update:
            self._web.page().runJavaScript(html)
        else:
            self._set_html_safe(html)
            self._placeholder.hide()
            self._web.show()
