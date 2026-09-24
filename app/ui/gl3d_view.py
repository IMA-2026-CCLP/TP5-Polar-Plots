"""
ui/gl3d_view.py — Vista nativa (pyqtgraph.opengl) de Superficie 3D. PILOTO de migración
fuera de Plotly/QWebEngineView (ver comentario en tab_directividad.py::_VIEW_CLASS_BY_MODE).

Reemplaza a BalloonView para el modo '3d' únicamente ('sphere' sigue en Plotly por ahora).
La matemática de la malla (interpolación, suavizado, combinación frente/atrás, cap del
cénit) se REUSA tal cual de plot/balloon.py (_build_hemisphere_grid) — sólo cambia cómo se
dibuja: acá con GLMeshItem/GLLinePlotItem/GLTextItem nativos en vez de un mesh3d de Plotly
dentro de un navegador embebido.

Ventajas sobre BalloonView para este modo: sin Chromium de por medio (arranca más rápido,
la app pesa menos), exportación y clic derecho nativos de Qt (sin los relays por consola
que necesitaba Plotly porque WebGL se comía los eventos).

Simplificaciones deliberadas de este primer piloto (fáciles de revisar/ajustar después):
  - Cámara: pyqtgraph.opengl no tiene proyección ortográfica nativa: la vista "Isométrica"
    queda en perspectiva (el ángulo isométrico sí es exacto, sólo cambia la proyección).
  - Grilla: Plotly dibujaba una caja con grid en los 3 ejes; acá se reemplaza por círculos
    de referencia (latitud/longitud), que tiene más sentido con datos inherentemente
    esféricos — el control de color/grosor de "Ejes / grilla" en Propiedades sigue vivo,
    ahora estiliza estos círculos.
  - No hay tooltip al pasar el mouse sobre la malla (Plotly sí lo tenía).

Bugs reales encontrados y corregidos tras la primera prueba en una PC real (ver historial de
commits para el detalle de cada uno):
  - El shader 'shaded' de pyqtgraph aplica una luz direccional fija que oscurecía casi a negro
    cualquier cara que no mirara hacia esa dirección — se sacó (sin shader = colores planos,
    fieles al dato).
  - El cénit se armaba como una malla de "cap" aparte (anillo + un punto ápice) y, como el
    anillo no es perfectamente plano (sigue la forma del dato), el ápice podía quedar más bajo
    que partes del anillo y dejar un hueco visible. Ahora el polo es una fila más de la propia
    grilla (todas las columnas colapsan al mismo punto): la superficie queda cerrada sin
    discontinuidades siempre, sin tratamiento especial.
  - La exportación usaba el último preset de cámara aplicado (self._camera) en vez de la
    posición VIVA (self._gl.cameraParams()), así que ignoraba cualquier rotación/zoom hecho a
    mano con el mouse. Ahora lee la cámara viva.
  - Crear y destruir un GLViewWidget nuevo en cada exportación resultó poco confiable (la
    segunda exportación seguida en el mismo proceso podía salir con errores de OpenGL e imagen
    en blanco) — ahora se reusa un único widget de exportación (_get_export_clone) de principio
    a fin de la sesión de trabajo.

API pública: espejo del subconjunto de BalloonView que usa TabDirectividad para el modo
'3d' (ver ui/tab_directividad.py::_ViewSection) — mismos nombres de método, misma firma.
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QStackedLayout, QLabel, QApplication, QHBoxLayout, QPushButton, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QImage, QColor, QPixmap

import pyqtgraph.opengl as gl

from ui.widgets import NumEdit

from plot.balloon import (
    _build_hemisphere_grid, FONT_SIZE, DEFAULT_SMOOTH_METHOD, DEFAULT_SMOOTH_WINDOW,
    DEFAULT_INTERP_DEG, COLORSCALES,
)
from core.data_store import freq_label
from core.symmetry_utils import apply_symmetry

# Presets de cámara — mismos ángulos que _CAMERA_PRESETS de ui/balloon_view.py (Plotly),
# convertidos de vector "eye" a (elevación, azimut) de pyqtgraph.opengl.
# GLViewWidget.cameraPosition(): pos = centro + dist·(cos(elev)cos(az), cos(elev)sin(az), sin(elev))
# — mismo Z-arriba que el resto de la app (X=frente/0°, Y=90°, Z=cénit), sin remapeo de ejes.
_CAMERA_PRESETS = {
    "top":     dict(elevation=90.0,    azimuth=0.0),
    "bottom":  dict(elevation=-90.0,   azimuth=0.0),
    "front":   dict(elevation=0.0,     azimuth=0.0),
    "back":    dict(elevation=0.0,     azimuth=180.0),
    "iso":     dict(elevation=35.264,  azimuth=45.0),     # ángulo isométrico clásico
    "default": dict(elevation=24.23,   azimuth=36.87),
}
_DEFAULT_DISTANCE = 2.6
_AXIS_LEN = 1.4
_AXES = (  # (vector, etiqueta, color) — idéntico a plot/balloon.py::_axes_traces
    ((_AXIS_LEN, 0, 0), "X (0°)",    QColor("#ff6b6b")),
    ((0, _AXIS_LEN, 0), "Y (90°)",   QColor("#51cf66")),
    ((0, 0, _AXIS_LEN), "Z (cénit)", QColor("#0d6dff")),
)


def _parse_color(c: str) -> list:
    """'#rrggbb' o 'rgb(r,g,b)' → [r,g,b] 0–1 (las paletas de plot/balloon.py mezclan los dos
    formatos: _seq() usa las de plotly.colors, en hex; PLOTLY_SCALES['Hot'] viene en rgb())."""
    if c.startswith('#'):
        c = c.lstrip('#')
        return [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    nums = c[c.index('(') + 1: c.index(')')].split(',')
    return [float(n) / 255.0 for n in nums[:3]]


def _colorscale_stops(name: str):
    """(t_stops, rgb_stops 0–1) desde COLORSCALES (listas [pos, color] de plot/balloon.py,
    mismas que usa Plotly) — listo para np.interp."""
    stops = COLORSCALES.get(name, COLORSCALES["Plasma"])
    if isinstance(stops, str):          # "Hot": nombre de escala nativa de Plotly, sin lista explícita
        import plotly.colors as pc
        stops = pc.PLOTLY_SCALES[stops]
    ts    = [float(t) for t, _ in stops]
    rgbs  = [_parse_color(c) for _, c in stops]
    return np.array(ts), np.array(rgbs)


def _map_colors(values: np.ndarray, vmin: float, vmax: float, colorscale: str) -> np.ndarray:
    """values (N,) en dB → colores RGBA (N,4) en 0–1."""
    ts, rgbs = _colorscale_stops(colorscale)
    span = (vmax - vmin) or 1.0
    t = np.clip((values - vmin) / span, 0.0, 1.0)
    rgba = np.empty((len(values), 4), dtype=np.float32)
    rgba[:, 0] = np.interp(t, ts, rgbs[:, 0])
    rgba[:, 1] = np.interp(t, ts, rgbs[:, 1])
    rgba[:, 2] = np.interp(t, ts, rgbs[:, 2])
    rgba[:, 3] = 1.0
    return rgba


class GL3DView(QWidget):
    """Ver docstring del módulo. Sólo modo '3d' (VIEW_MODES de BalloonView no aplica acá:
    esta clase se instancia únicamente para ese modo, ver _VIEW_CLASS_BY_MODE)."""

    log = pyqtSignal(str)
    context_menu_requested = pyqtSignal(int, int)   # x, y en píxeles locales del widget
    intersect_requested    = pyqtSignal(float)      # elevación elegida (°) — "Intersectar"

    _EXPORT_FORMATS = ('png', 'jpeg', 'webp')   # sin SVG: es una malla rasterizada, no vectorial

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels:     np.ndarray | None = None
        self._azimuths:   np.ndarray | None = None
        self._elevations: np.ndarray | None = None
        self._bands:      np.ndarray | None = None
        self._band_index: int = 0
        self._colorscale: str = "Plasma"
        self._min_db:     float | None = None
        self._max_db:     float | None = None
        self._show_info:  bool = False
        self._axis_color: str | None = None
        self._axis_width: float = 1
        self._style:      dict = {}
        self._camera      = dict(_CAMERA_PRESETS["default"])
        self._current_items: list = []
        self._export_clone = None   # GLViewWidget reusado entre exportaciones, ver _get_export_clone
        self._cut_elevation: float = 0.0   # elevación elegida (0°–90°), ver _make_cut_ring_items
        self._cut_visible:   bool  = False
        # último grid calculado (para reconstruir los mismos items al exportar sin
        # recalcular la malla — ver export_image)
        self._last_grid = None

        layout = QStackedLayout(self)
        layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        layout.setContentsMargins(0, 0, 0, 0)

        self._gl = gl.GLViewWidget()
        self._gl.setBackgroundColor('#ffffff')
        self._gl.installEventFilter(self)

        self._placeholder = QLabel("Calculá la directividad\npara ver el patrón polar aquí.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("background:#ffffff; color:#7a7a7a; font-size:11pt; border:none;")
        self._placeholder.setFont(QFont("Segoe UI", 12))

        layout.addWidget(self._gl)
        layout.addWidget(self._placeholder)
        self._placeholder.raise_()

        # Overlays 2D (info + colorbar): hijos directos del widget, por encima de todo.
        self._info_label = QLabel(self)
        self._info_label.setStyleSheet(
            "background: rgba(255,255,255,0.85); color:#1a1a1a; padding:4px 8px; "
            "border:1px solid #c8c8c8; border-radius:3px; font-size:10px;")
        self._info_label.move(8, 8)
        self._info_label.hide()

        self._colorbar = QLabel(self)
        self._colorbar.hide()

        self._build_cut_plane_controls()
        self._apply_camera()

    def _build_cut_plane_controls(self):
        """Controles del plano de corte XY (abajo a la izquierda): elegir la elevación
        (0°–90°), mostrarla en la escena (plano de referencia + la curva real a esa elevación),
        e "Intersectar" — manda esa misma elevación al selector "Elevación" que ya tiene Polar 2D
        (Parámetros ▸ Polar 2D), que muestra el contorno medido en ese ángulo. No se recalcula
        una intersección geométrica aparte contra la malla (que además de compleja daría un
        resultado distinto: acá el radio codifica el nivel medido, no es una esfera real, así
        que la curva a una elevación no es plana — el plano de referencia se muestra al lado
        para que se note la diferencia) — se reusa el corte por elevación que Polar 2D ya sabe
        dibujar, sólo que elegido visualmente desde acá."""
        box = QWidget(self)
        box.setStyleSheet(
            "background: rgba(255,255,255,0.9); border:1px solid #c8c8c8; border-radius:3px;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)

        self._chk_cut = QCheckBox("Resaltar curva")
        self._chk_cut.setToolTip(
            "Muestra el plano de referencia y la curva real a esta elevación — es una de las "
            "curvas apiladas que arman la superficie (sigue el relieve real, no es plana como "
            "el plano). Es exactamente lo que 'Intersectar' va a mostrar en Polar 2D.")
        self._chk_cut.toggled.connect(self._on_cut_toggled)
        lay.addWidget(self._chk_cut)

        lay.addWidget(QLabel("Elevación:"))
        btn_down = QPushButton("◀")
        btn_down.setFixedWidth(24)
        btn_down.setAutoDefault(False)
        btn_down.setToolTip("-10°")
        btn_down.clicked.connect(lambda: self._step_cut_elevation(-10))
        lay.addWidget(btn_down)

        self._ne_cut = NumEdit()
        self._ne_cut.setRange(0, 90)
        self._ne_cut.setDecimals(0)
        self._ne_cut.setValue(0)
        self._ne_cut.setFixedWidth(36)
        self._ne_cut.setToolTip("0° a 90°. 'Aceptar' (o Enter) lo aplica; 'Intersectar' lo manda a Polar 2D.")
        self._ne_cut.returnPressed.connect(self._apply_cut_elevation)
        lay.addWidget(self._ne_cut)
        lay.addWidget(QLabel("°"))

        btn_up = QPushButton("▶")
        btn_up.setFixedWidth(24)
        btn_up.setAutoDefault(False)
        btn_up.setToolTip("+10°")
        btn_up.clicked.connect(lambda: self._step_cut_elevation(10))
        lay.addWidget(btn_up)

        btn_ok = QPushButton("Aceptar")
        btn_ok.setAutoDefault(False)
        btn_ok.setToolTip("Aplica el valor tipeado (mueve el plano y la curva resaltada).")
        btn_ok.clicked.connect(self._apply_cut_elevation)
        lay.addWidget(btn_ok)

        btn_go = QPushButton("Intersectar →")
        btn_go.setToolTip("Muestra en Polar 2D el contorno medido en esta elevación.")
        btn_go.setAutoDefault(False)
        btn_go.clicked.connect(self._on_intersect_clicked)
        lay.addWidget(btn_go)

        box.adjustSize()
        self._cut_box = box
        self._cut_box.hide()   # se muestra recién cuando hay datos (ver _render_inner)

    def _on_cut_toggled(self, on: bool):
        self._cut_visible = on
        if self._last_grid is not None:
            self._render()

    def _step_cut_elevation(self, delta: float):
        self._ne_cut.setValue(max(0, min(90, self._ne_cut.value() + delta)))
        self._apply_cut_elevation()

    def _apply_cut_elevation(self):
        # No se aplica en cada tecla tipeada (textChanged) — re-renderiza toda la malla y
        # resultaba molesto/lento mientras se escribe un número de más de un dígito.
        self._cut_elevation = self._ne_cut.value()
        if self._cut_visible and self._last_grid is not None:
            self._render()

    def _on_intersect_clicked(self):
        self._apply_cut_elevation()
        self.intersect_requested.emit(self._ne_cut.value())

    # ── API pública ──────────────────────────────────────────────────────

    def mapToGlobal(self, pos):
        return self._gl.mapToGlobal(pos)

    def eventFilter(self, obj, event):
        if obj is self._gl and event.type() == event.Type.ContextMenu:
            self.context_menu_requested.emit(event.pos().x(), event.pos().y())
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_overlays()

    def _reposition_overlays(self):
        if self._colorbar.isVisible():
            self._colorbar.move(self.width() - self._colorbar.width() - 28, 10)
        self._cut_box.move(8, self.height() - self._cut_box.height() - 8)

    # — no aplican a este modo, pero _ViewSection los llama para los 4 tipos de vista —
    def set_view_mode(self, mode):
        pass

    def set_tick_font_size(self, size):
        pass

    def set_plane(self, plane):
        pass

    def set_el_index(self, idx):
        pass

    def set_normalize(self, value):
        pass

    def apply_theme(self, palette):
        pass   # el gráfico 3D es siempre blanco, no sigue el tema claro/oscuro de la app

    def show_placeholder(self):
        self._placeholder.show()
        self._placeholder.raise_()

    def set_data(self, levels, azimuths, elevations, bands, band_index=0,
                 symmetry_type="none", ref_spectrum=None, spec_global=True):
        # ref_spectrum/spec_global no aplican a este modo (son del Espectro); se aceptan
        # igual porque _ViewSection.set_data llama a todas las vistas con los mismos kwargs.
        levels_s, az_s, el_s = apply_symmetry(levels, azimuths, elevations, symmetry_type)
        self._levels     = levels_s
        self._azimuths   = az_s
        self._elevations = el_s
        self._bands      = bands
        self._band_index = band_index
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

    def set_db_range(self, min_db, max_db):
        self._min_db = min_db
        self._max_db = max_db
        if self._levels is not None:
            self._render()

    def set_show_info(self, show: bool):
        self._show_info = show
        if self._levels is None:
            return
        self._render()

    def set_axis_style(self, color, width):
        self._axis_color = color
        self._axis_width = width
        if self._levels is not None:
            self._render()

    def set_style(self, style: dict):
        self._style = style or {}
        self._gl.setBackgroundColor(self._style.get('bg_color') or '#ffffff')
        if self._levels is not None:
            self._render()

    def set_camera_view(self, view: str):
        preset = _CAMERA_PRESETS.get(view)
        if preset is None:
            return
        self._camera = dict(preset)
        self._apply_camera()

    def _apply_camera(self):
        self._gl.setCameraPosition(distance=_DEFAULT_DISTANCE, **self._camera)

    # ── Render ───────────────────────────────────────────────────────────

    def _render(self):
        try:
            self._render_inner()
        except Exception as exc:
            import traceback
            self.log.emit(f"[ERROR] 3d render: {exc}\n{traceback.format_exc()}")

    def _render_inner(self):
        self._placeholder.hide()
        self._cut_box.show()
        self._cut_box.raise_()
        self._reposition_overlays()   # reubica el control ahora que ya tiene su tamaño final
        style = self._style
        lev_2d = self._levels[:, :, self._band_index]
        band_hz = float(self._bands[self._band_index])

        R_dB, phi_rad, elev_rad, vmin, vmax, zenith_dB = _build_hemisphere_grid(
            lev_2d, self._azimuths, self._elevations,
            interp_deg=style.get('interp_deg', DEFAULT_INTERP_DEG),
            smoothing=style.get('smoothing', 0.0),
            smoothing_method=style.get('smoothing_method', DEFAULT_SMOOTH_METHOD),
            smoothing_window=int(style.get('smoothing_window', DEFAULT_SMOOTH_WINDOW)),
        )
        # El spline de interpolación (RectBivariateSpline, en _build_hemisphere_grid) puede
        # devolver NaN/inf en condiciones borde (huecos de datos, mic caído, etc.) — un vértice
        # así queda en una posición/color indefinidos, que la GPU suele pintar blanco con
        # triángulos degenerados y filosos justo ahí (visto cerca del cénit, donde el spline es
        # más delicado). Se reemplaza por vmin: no "inventa" un valor alto, achica ese punto.
        if not np.isfinite(R_dB).all():
            R_dB = np.nan_to_num(R_dB, nan=vmin, posinf=vmax, neginf=vmin)

        cmin = self._min_db if self._min_db is not None else vmin
        cmax = self._max_db if self._max_db is not None else vmax
        span = (vmax - vmin) or 1.0
        R_clip = np.clip(R_dB, cmin, cmax)
        R_r    = np.clip((R_dB - vmin) / span, 0.01, 1.0)

        E, P = np.meshgrid(elev_rad, phi_rad, indexing='ij')
        X = R_r * np.cos(E) * np.cos(P)
        Y = R_r * np.cos(E) * np.sin(P)
        Z = R_r * np.sin(E)
        C = R_clip

        # Costura acimutal (φ=0° y φ=360° son el mismo meridiano, primera y última columna de
        # la grilla): el spline de interpolación no garantiza que ambos bordes coincidan exacto
        # — medido hasta ~0,08 de diferencia en radio normalizado, nada que ver con redondeo de
        # punto flotante — y como son dos columnas de vértices DISTINTAS, esa diferencia dejaba
        # una grieta angosta visible ahí (justo donde estaba la marca blanca, cerca de X/0°). Se
        # fuerza la última columna a coincidir exacto con la primera: cierra siempre, sin
        # depender de que el spline sea perfectamente periódico.
        X[:, -1], Y[:, -1], Z[:, -1], C[:, -1] = X[:, 0], Y[:, 0], Z[:, 0], C[:, 0]

        # Cierre del cénit: se agrega el polo como una fila más de la MISMA grilla (todas las
        # columnas colapsan al mismo punto XYZ) en vez de una malla de "cap" aparte — así la
        # triangulación estándar en abanico cierra siempre sola, sin depender de que el último
        # anillo sea plano (no lo es: sigue la forma del dato, y un cap separado con un solo
        # punto ápice podía quedar más bajo que partes del anillo y dejar un hueco visible).
        if zenith_dB is not None and np.isfinite(zenith_dB):
            n_p = X.shape[1]
            z_norm  = float(np.clip((zenith_dB - vmin) / span, 0.01, 1.0))
            z_color = float(np.clip(zenith_dB, cmin, cmax))
            X = np.vstack([X, np.zeros(n_p)])
            Y = np.vstack([Y, np.zeros(n_p)])
            Z = np.vstack([Z, np.full(n_p, z_norm)])
            C = np.vstack([C, np.full(n_p, z_color)])

        self._last_grid = dict(X=X, Y=Y, Z=Z, C=C, cmin=cmin, cmax=cmax,
                                zenith_dB=zenith_dB, vmin=vmin, span=span,
                                elev_deg=np.degrees(elev_rad))   # una fila del grid por elevación medida/interpolada

        for it in self._current_items:
            self._gl.removeItem(it)
        self._current_items = self._build_items(self._last_grid)
        for it in self._current_items:
            self._gl.addItem(it)

        self._update_colorbar(cmin, cmax)

        if self._show_info:
            zenith_str = f"<br><b>Cénit:</b> {zenith_dB:.1f} dB" if zenith_dB is not None else ""
            self._info_label.setText(
                f"<b>Banda:</b> {freq_label(band_hz)} Hz<br>"
                f"<b>Máx:</b> {vmax:.1f} dB<br>"
                f"<b>Mín:</b> {vmin:.1f} dB{zenith_str}<br>"
                f"<b>Rango dinámico:</b> {vmax - vmin:.1f} dB"
            )
            self._info_label.adjustSize()
            self._info_label.show()
        else:
            self._info_label.hide()

    # ── Construcción de items (usado tanto por el render en pantalla como por export_image,
    #    que arma los mismos items sobre un GLViewWidget clon fuera de pantalla) ───────────

    def _build_items(self, g: dict) -> list:
        items = [self._make_surface_item(g)]
        items += self._make_axis_items()
        items += self._make_grid_items()
        if self._cut_visible:
            items += self._make_cut_ring_items(g)
        return items

    def _make_cut_ring_items(self, g: dict) -> list:
        """Plano de referencia (chato, Z constante) + la curva REAL a esa elevación resaltada
        sobre la propia malla (fila de la grilla más cercana) — a propósito uno al lado del otro:
        acá el radio codifica el nivel medido, no es una esfera real, así que la curva a una
        elevación no es plana (sube y baja siguiendo el nivel de cada azimut) — el plano se ve
        chato y la curva no, y esa diferencia es la prueba visual de por qué. La curva es
        exactamente lo que "Intersectar" manda a Polar 2D; el plano es sólo referencia, no se
        usa para calcular nada."""
        items = [self._make_reference_plane_item()]
        elev_deg = g.get('elev_deg')
        if elev_deg is None or not len(elev_deg):
            return items
        row = int(np.argmin(np.abs(elev_deg - np.clip(self._cut_elevation, 0, 90))))
        X, Y, Z = g['X'], g['Y'], g['Z']
        pts = np.stack([X[row], Y[row], Z[row]], axis=-1)
        color = (0.05, 0.05, 0.05, 1.0)   # casi negro: contraste fuerte contra cualquier color de la malla
        ring = gl.GLLinePlotItem(pos=pts, color=color, width=5, antialias=True)
        # Puntito en cada vértice: ayuda a ver que la curva sigue el relieve real (no es plana).
        dots = gl.GLScatterPlotItem(pos=pts[::4], color=color, size=6, pxMode=True)
        items += [ring, dots]
        return items

    def _make_reference_plane_item(self):
        """Disco chato y semitransparente a la altura Z que tendría un punto a esta elevación
        en una esfera de radio 1 — sólo referencia visual, nunca se usa para calcular nada."""
        e = np.radians(np.clip(self._cut_elevation, 0, 90))
        z = float(np.sin(e))
        radius = 1.3
        n = 48
        phi = np.linspace(0, 2 * np.pi, n, endpoint=False)
        rim = np.stack([radius * np.cos(phi), radius * np.sin(phi), np.full(n, z)], axis=-1)
        verts = np.vstack([rim, [[0.0, 0.0, z]]])   # centro al final
        center = n
        faces = np.array([[k, (k + 1) % n, center] for k in range(n)])
        color = QColor("#2F6DB5")
        colors = np.tile([color.redF(), color.greenF(), color.blueF(), 0.18], (len(verts), 1))
        md = gl.MeshData(vertexes=verts, faces=faces, vertexColors=colors)
        return gl.GLMeshItem(meshdata=md, smooth=False, glOptions='translucent')

    def _make_surface_item(self, g: dict):
        # El polo (cénit) ya viene como una fila más de esta misma grilla si zenith_dB no es
        # None (ver _render_inner) — todas sus columnas coinciden en un mismo punto XYZ, así
        # que la triangulación de abajo cierra sola en un abanico sin ningún tratamiento
        # especial: superficie sin agujero ni discontinuidad en el cénit, siempre.
        X, Y, Z, C = g['X'], g['Y'], g['Z'], g['C']
        n_e, n_p = X.shape
        verts  = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
        colors = _map_colors(C.reshape(-1), g['cmin'], g['cmax'], self._colorscale)

        i = np.arange(n_e - 1)[:, None]
        j = np.arange(n_p - 1)[None, :]
        idx = i * n_p + j
        a, b, c, d = idx, idx + 1, idx + n_p, idx + n_p + 1
        tri1 = np.stack([a, b, c], axis=-1).reshape(-1, 3)
        tri2 = np.stack([b, d, c], axis=-1).reshape(-1, 3)
        faces = np.concatenate([tri1, tri2], axis=0)

        md = gl.MeshData(vertexes=verts, faces=faces, vertexColors=colors)
        # Sin shader (colores planos, tal cual el dato): el shader 'shaded' de pyqtgraph aplica
        # una luz direccional fija (rgb *= 0.2 + dot(normal, luz)) que oscurece casi a negro
        # cualquier cara que no mire hacia esa dirección — con una malla tipo globo, la mayoría
        # de las caras quedaban así sin importar su color real.
        return gl.GLMeshItem(meshdata=md, smooth=True, glOptions='opaque')

    def _make_axis_items(self) -> list:
        width = float(self._style.get('axis_line_width', 3))
        label_size = int(self._style.get('axis_label_size', FONT_SIZE))
        items = []
        for vec, label, color in _AXES:
            rgba = (color.redF(), color.greenF(), color.blueF(), 1.0)
            items.append(gl.GLLinePlotItem(pos=np.array([[0, 0, 0], vec]), color=rgba,
                                            width=width, antialias=True))
            items.append(gl.GLTextItem(pos=np.array(vec, dtype=float), text=label, color=color,
                                        font=QFont("Segoe UI", label_size)))
        return items

    def _make_grid_items(self) -> list:
        """Círculos de referencia (latitud/longitud) — ver nota de diseño en el docstring
        del módulo. Estilizados por 'Ejes / grilla' en Propiedades (mismo control que antes
        manejaba la grilla de caja de Plotly)."""
        qc = QColor(self._axis_color or '#2e3248')
        color = (qc.redF(), qc.greenF(), qc.blueF(), 0.6)
        width = float(self._axis_width or 1)
        items = []
        phi = np.linspace(0, 2 * np.pi, 73)
        for elev_deg in (0, 30, 60, 90):
            e = np.radians(elev_deg)
            r = np.cos(e)
            pts = np.stack([r * np.cos(phi), r * np.sin(phi), np.full_like(phi, np.sin(e))], axis=-1)
            items.append(gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True))
        theta = np.linspace(0, np.pi / 2, 37)
        for az_deg in range(0, 360, 45):
            a = np.radians(az_deg)
            pts = np.stack([np.cos(theta) * np.cos(a), np.cos(theta) * np.sin(a), np.sin(theta)], axis=-1)
            items.append(gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True))
        return items

    def _update_colorbar(self, cmin: float, cmax: float):
        w, h = 18, 120
        ts, rgbs = _colorscale_stops(self._colorscale)
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        for y in range(h):
            t = 1.0 - y / (h - 1)
            r = float(np.interp(t, ts, rgbs[:, 0]))
            gg = float(np.interp(t, ts, rgbs[:, 1]))
            b = float(np.interp(t, ts, rgbs[:, 2]))
            color = QColor(int(r * 255), int(gg * 255), int(b * 255))
            for x in range(w):
                img.setPixelColor(x, y, color)
        self._colorbar.setPixmap(QPixmap.fromImage(img))
        self._colorbar.setFixedSize(w, h)
        self._colorbar.move(self.width() - w - 28, 10)
        self._colorbar.setToolTip(f"{cmax:.1f} dB (arriba) — {cmin:.1f} dB (abajo)")
        self._colorbar.show()

    # ── Exportación ──────────────────────────────────────────────────────

    def _get_export_clone(self):
        """GLViewWidget fuera de pantalla para exportar, creado UNA sola vez y reusado en cada
        exportación (en vez de crear/destruir uno por llamada): crear varios QOpenGLWidget
        seguidos en el mismo proceso resultó poco confiable acá (la segunda exportación salía
        con errores de OpenGL y la imagen quedaba prácticamente en blanco) — reusar el mismo
        contexto de principio a fin lo evita. Se posiciona fuera del área visible del escritorio
        (move a coordenadas negativas) en vez de WA_DontShowOnScreen: un QOpenGLWidget necesita
        una ventana nativa real para poder crear su contexto OpenGL."""
        if self._export_clone is None:
            self._export_clone = gl.GLViewWidget()
            self._export_clone.move(-4000, -4000)
            self._export_clone.show()
        return self._export_clone

    def export_image(self, path: str, dpi: int = 300, fmt: str = 'png', on_done=None, size_cm=None):
        """Tamaño físico fijo (Opciones ▸ Gráficos ▸ Imágenes); el DPI sólo define los píxeles
        (ver ui/export_utils.py). Se renderiza en un GLViewWidget fuera de pantalla (reusado
        entre llamadas, ver _get_export_clone), al tamaño final exacto — no es una captura del
        panel en pantalla."""
        if self._last_grid is None:
            self.log.emit("[Dir] Sin datos para exportar.")
            if on_done:
                on_done(False)
            return
        fmt = fmt if fmt in self._EXPORT_FORMATS else 'png'

        from ui.export_utils import get_export_size_cm, logical_px, set_png_dpi
        w_cm, h_cm = size_cm or get_export_size_cm()
        k = dpi / 96.0
        W = max(1, int(round(logical_px(w_cm) * k)))
        H = max(1, int(round(logical_px(h_cm) * k)))

        clone = self._get_export_clone()
        clone.setBackgroundColor(self._style.get('bg_color') or '#ffffff')
        clone.resize(W, H)
        for item in list(clone.items):
            clone.removeItem(item)
        for item in self._build_items(self._last_grid):
            clone.addItem(item)
        # Cámara VIVA (self._gl.cameraParams()), no la del último preset aplicado (self._camera):
        # si no, la imagen exportada no coincidía con la rotación/zoom hechos a mano con el mouse.
        clone.setCameraParams(**self._gl.cameraParams())

        def _grab():
            ok = False
            # grabFramebuffer() puede capturar el cursor del mouse dentro de la imagen (bug
            # conocido de Qt/Windows con QOpenGLWidget, no algo que dibuje esta vista) — se oculta
            # el cursor justo antes de capturar y se restaura enseguida después.
            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            try:
                img = clone.grabFramebuffer()
                ok = (not img.isNull()) and img.save(path)
                if ok and fmt != 'svg':
                    set_png_dpi(path, dpi)
                if ok:
                    self.log.emit(f"[Dir] Imagen guardada → {path} ({dpi} DPI, {fmt})")
                else:
                    self.log.emit(f"[ERROR] No se pudo guardar la imagen en {path} "
                                   "(¿sin soporte OpenGL en este equipo?)")
            except Exception as exc:
                self.log.emit(f"[ERROR] Exportando 3D: {exc}")
            finally:
                QApplication.restoreOverrideCursor()
                if on_done:
                    on_done(ok)

        # Da tiempo a que la ventana nativa fuera de pantalla se realice / el contexto se
        # inicialice antes de pedirle el framebuffer.
        QTimer.singleShot(250, _grab)
