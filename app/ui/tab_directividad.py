"""
ui/tab_directividad.py — Directividad: cómputo y visualización multi-panel.
Los controles están en el ribbon global (ui/ribbon.py).
"""
import io
import re
import sys
import traceback
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QCheckBox, QScrollArea,
    QGridLayout, QFrame, QProgressDialog, QFileDialog, QPushButton, QGroupBox,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QComboBox,
    QColorDialog, QInputDialog, QSplitter, QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QPoint
from PyQt6.QtGui import QColor, QKeySequence, QShortcut

from ui.balloon_view import BalloonView
from ui.gl3d_view import GL3DView
from ui.polar2d_view import Polar2DView
from ui.spectrum_view import SpectrumView
from ui.band_selector import BandSelectorWidget
from ui.widgets import NumEdit as _NumEdit
from plot.balloon import (COLORSCALES, _COMPARE_COLORS, FONT_SIZE, DEFAULT_SMOOTH_METHOD, DEFAULT_SMOOTH_WINDOW,
                          DEFAULT_INTERP_KIND, DEFAULT_INTERP_DEG)
from core.data_store import freq_label
from core.worker import Worker, begin as _begin, end as _end, report as _report

# polar2d y spectrum ya migraron a pyqtgraph nativo (Polar2DView/SpectrumView); 3d migró a
# pyqtgraph.opengl (GL3DView, ver ui/gl3d_view.py) como piloto de la migración fuera de
# Plotly/QWebEngineView; esfera sigue en Plotly (BalloonView) hasta confirmar el piloto.
_VIEW_CLASS_BY_MODE = {
    "3d":       GL3DView,
    "sphere":   BalloonView,
    "polar2d":  Polar2DView,
    "spectrum": SpectrumView,
}

_MODE_LABELS = {
    "3d":       "superficie_3d",
    "sphere":   "esfera",
    "polar2d":  "polar_2d",
    "spectrum": "espectro",
}

_DASH_STYLES = ["solid", "dash", "dot", "dashdot", "longdash"]

# Fondo blanco fijo en los 4 tipos de gráfico, independiente del tema
# claro/oscuro de la app (pedido explícito: "jamás oscuro"). text_color
# acompaña al bg_color para que las etiquetas no queden claras sobre
# fondo blanco si la app está en tema oscuro.
_DEFAULT_STYLE_BY_MODE = {
    "3d":       {"bg_color": "#ffffff", "text_color": "#000000", "smoothing_method": DEFAULT_SMOOTH_METHOD,
                 "smoothing_window": DEFAULT_SMOOTH_WINDOW, "interp_deg": DEFAULT_INTERP_DEG,
                 "cut_visible": False, "cut_elevation": 0.0, "geometry_mode": "origin",
                 "show_ref_plane": True, "show_hemisphere_grid": True},
    "sphere":   {"bg_color": "#ffffff", "text_color": "#000000", "smoothing_method": DEFAULT_SMOOTH_METHOD,
                 "smoothing_window": DEFAULT_SMOOTH_WINDOW, "interp_deg": DEFAULT_INTERP_DEG},
    "polar2d":  {
        "bg_color":         "#ffffff",
        "text_color":       "#1a1a1a",
        "ring_color":       "#000000",
        "ring_font_size":   FONT_SIZE,
        "ring_step":        5.0,
        "ring_label_angle": 45.0,
        "legend_font_size": FONT_SIZE,
        "line_width":       2.5,
        "smoothing_method": DEFAULT_SMOOTH_METHOD,
        "smoothing_window": DEFAULT_SMOOTH_WINDOW,
        "interp_kind":      DEFAULT_INTERP_KIND,
        "interp_deg":       DEFAULT_INTERP_DEG,
    },
    "spectrum": {"bg_color": "#ffffff", "text_color": "#000000", "bar_color": "#146B64"},
}
_DEFAULT_MIN_DB_BY_MODE = {"polar2d": -20.0}
_DEFAULT_MAX_DB_BY_MODE = {"polar2d": 10.0}


# ── Worker para cómputo batch (todo el audio + todas las notas) ───────────────

_PROGRESS_RE = re.compile(r'(\d+)/(\d+)\s+az=')


class _ComputeAllWorker(QThread):
    log               = pyqtSignal(str)
    progress          = pyqtSignal(int, int, str)   # actual, total, etiqueta (por item)
    overall_progress  = pyqtSignal(float)           # 0.0–1.0, combina item + posición interna
    all_done          = pyqtSignal()
    error             = pyqtSignal(str)

    def __init__(self, ma, bands, ref_az, ref_th, parent=None):
        super().__init__(parent)
        self._ma     = ma
        self._bands  = bands
        self._ref_az = ref_az
        self._ref_th = ref_th
        self._item_index = 0
        self._item_total = 1

    def run(self):
        worker = self

        class _Cap(io.TextIOBase):
            def __init__(self, sig):
                super().__init__(); self._s = sig
            def write(self, t):
                if t.strip():
                    self._s.emit(t.rstrip())
                    m = _PROGRESS_RE.search(t)
                    if m:
                        sub_done, sub_total = int(m.group(1)), int(m.group(2))
                        frac_item = sub_done / sub_total if sub_total else 0.0
                        overall = (worker._item_index + frac_item) / worker._item_total
                        worker.overall_progress.emit(min(overall, 1.0))
                        _report(int(min(overall, 1.0) * 1000), 1000)      # barra de la barra de estado
                return len(t)
            def flush(self): pass

        old_out = sys.stdout
        sys.stdout = _Cap(self.log)
        _begin("Calculando directividad…")
        try:
            tasks = [("Todo el audio", self._ma)]
            if self._ma.notes:
                tasks += list(self._ma.notes.items())

            total = len(tasks)
            self._item_total = total
            for i, (label, ma) in enumerate(tasks):
                self._item_index = i
                self.progress.emit(i, total, label)
                ma.compute_directivity(
                    bands          = self._bands,
                    ref_azimuth    = self._ref_az,
                    ref_theta_plot = self._ref_th,
                )
                self.log.emit(f"[Directividad] {label} — OK")

            self.progress.emit(total, total, "")
            self.overall_progress.emit(1.0)
            self.all_done.emit()
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            sys.stdout = old_out
            _end("Calculando directividad…")


class _CompareEditor(QGroupBox):
    """Pestaña "Comparación" del Polar 2D: lista en 2 columnas, una fila por banda con [activar] [color] [grosor]
    [tipo de línea], más la leyenda. Sin deslizables. Los cambios se avisan por on_change (edición en vivo)."""

    _POS = [("Arriba a la derecha", "top-right"), ("Arriba a la izquierda", "top-left"),
            ("Abajo a la derecha", "bottom-right"), ("Abajo a la izquierda", "bottom-left")]

    def __init__(self, sec, dlg, parent=None):
        super().__init__("Comparación", parent)
        self.on_change = None
        bands = sec.view._bands
        n = 0 if bands is None else len(bands)
        styles = {int(k): v for k, v in sec._compare_styles.items()}
        sel = set(sec._compare_indices or [])

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addWidget(QLabel("Activá dos o más bandas para superponerlas y elegí cómo se dibuja cada una:"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(3)
        self._rows = {}                        # banda -> (check, color, grosor, tipo)
        per_col = (n + 1) // 2
        for i in range(n):
            st = styles.get(i, {})
            cb = QCheckBox(f"{freq_label(float(bands[i]))} Hz")
            cb.setMinimumWidth(78)
            cb.setChecked(i in sel)
            btn = sec._make_color_button(dlg, st.get('color', _COMPARE_COLORS[i % len(_COMPARE_COLORS)]))
            w = _NumEdit()
            w.setFixedWidth(44)
            w.setRange(0.5, 10.0)
            w.setValue(st.get('width', 2.5))
            w.setToolTip("Grosor de la línea")
            dash = QComboBox()
            dash.addItems(_DASH_STYLES)
            dash.setCurrentText(st.get('dash', 'solid'))
            dash.setToolTip("Tipo de línea")
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            for x in (cb, btn, w, dash):
                h.addWidget(x)
            grid.addWidget(row, i % per_col, i // per_col)
            self._rows[i] = (cb, btn, w, dash)
            cb.toggled.connect(lambda on, k=i: self._toggled(k, on))
            btn.on_change = self._changed
            w.textChanged.connect(self._changed)
            dash.currentTextChanged.connect(self._changed)
            self._set_row_enabled(i, i in sel)
        lay.addLayout(grid)

        form = QFormLayout()
        self._show = QCheckBox("Mostrar leyenda")
        self._show.setChecked(sec._style.get('show_legend', True))
        self._show.toggled.connect(self._changed)
        self._pos = QComboBox()
        for label, val in self._POS:
            self._pos.addItem(label, val)
        self._pos.setCurrentIndex(max(0, self._pos.findData(sec._style.get('legend_pos', 'top-right'))))
        self._pos.currentIndexChanged.connect(self._changed)
        form.addRow(self._show)
        form.addRow("Posición de la leyenda:", self._pos)
        lay.addLayout(form)

    def _set_row_enabled(self, i, on):
        _, btn, w, dash = self._rows[i]
        for x in (btn, w, dash):
            x.setEnabled(on)

    def _toggled(self, i, on):
        self._set_row_enabled(i, on)
        self._changed()

    def _changed(self, *_):
        if self.on_change:
            self.on_change()

    def state(self):
        """(bandas activas, {banda: estilo}, {'pos':…, 'show':…})"""
        sel = [i for i, (cb, *_r) in self._rows.items() if cb.isChecked()]
        styles = {i: {'color': self._rows[i][1].color_hex, 'width': self._rows[i][2].value(),
                      'dash': self._rows[i][3].currentText()} for i in sel}
        return sel, styles, {'pos': self._pos.currentData(), 'show': self._show.isChecked()}


class _ViewSection(QWidget):
    """
    Panel para un único modo de visualización.
    El título va en la barra del QDockWidget que lo contiene (ver
    TabDirectividad._make_right_panel). La escala (min/max dB), la
    autoescala y el guardado de imagen se acceden con click derecho sobre
    el gráfico, para no restarle espacio vertical al plot con una barra fija.
    """
    log                  = pyqtSignal(str)
    save_requested       = pyqtSignal(str)   # emite el modo ("3d", "sphere", etc.)
    properties_requested = pyqtSignal()      # pide abrir/actualizar el panel de Propiedades
    properties_applied   = pyqtSignal()      # se aplicó un cambio de Propiedades (para Ctrl+Z)
    zoom_requested       = pyqtSignal(str)   # 'Ver en grande' / volver (emite el modo)

    def __init__(self, title: str, mode: str, parent=None):
        super().__init__(parent)
        self._mode   = mode
        self._zoomed = False
        self._open_tab = None       # pestaña a mostrar al abrir Propiedades
        self._min_db: float | None = _DEFAULT_MIN_DB_BY_MODE.get(mode)
        self._max_db: float | None = _DEFAULT_MAX_DB_BY_MODE.get(mode)
        self._compare_indices: list | None = None   # sólo relevante para polar2d
        self._compare_styles: dict = {}             # {band_index: {'color','width','dash'}}
        self._tick_font_size: float = FONT_SIZE
        self._axis_color: str | None = None         # color de grilla 3D (3d/sphere), None = tema
        self._axis_width: float = 1                 # grosor de grilla 3D
        self._style: dict = dict(_DEFAULT_STYLE_BY_MODE.get(mode, {}))   # overrides (bg_color, etc.)
        self._props_undo_stack: list[dict] = []   # snapshots previos a cada "Aplicar" (Ctrl+Z)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.view = _VIEW_CLASS_BY_MODE[mode]()
        self.view.set_view_mode(mode)
        self.view.log.connect(self.log)
        self.view.set_style(self._style)
        self.view.set_db_range(self._min_db, self._max_db)
        self.view.set_tick_font_size(self._tick_font_size)
        lay.addWidget(self.view, 1)

        # No se usa QWebEngineView.customContextMenuRequested: sobre el canvas
        # WebGL de las escenas 3D, Plotly captura el botón derecho para
        # panear la cámara y bloquea el contextmenu nativo, así que Qt nunca
        # ve el evento ahí. En su lugar, el propio HTML reenvía el click
        # derecho por consola (ver plot/balloon.py _wrap_html), capturado acá.
        self.view.context_menu_requested.connect(self._show_context_menu)

        self.setMinimumHeight(80)

    def set_zoomed(self, on: bool):
        self._zoomed = on

    def _show_context_menu(self, x: int, y: int):
        import time
        if getattr(self, '_menu_open', False) or time.monotonic() - getattr(self, '_menu_closed_at', 0) < 0.4:
            return       # ya hay un menú abierto (o se acaba de cerrar): no encadenar otro
        self._menu_open = True
        try:
            self._show_context_menu_impl(x, y)
        finally:
            self._menu_open = False
            self._menu_closed_at = time.monotonic()

    def _show_context_menu_impl(self, x: int, y: int):
        pos = QPoint(x, y)
        menu = QMenu(self)

        act_zoom = menu.addAction("Volver a los 4 gráficos" if self._zoomed else "Ver en grande")
        menu.addSeparator()

        act_top = act_bottom = act_front = act_back = act_iso = act_default = None
        if self._mode in ("3d", "sphere"):
            view_menu  = menu.addMenu("Vista")
            act_default = view_menu.addAction("Predeterminada")
            act_iso    = view_menu.addAction("Isométrica")
            view_menu.addSeparator()
            act_top    = view_menu.addAction("Arriba")
            act_bottom = view_menu.addAction("Abajo")
            act_front  = view_menu.addAction("Frente")
            act_back   = view_menu.addAction("Atrás")
            menu.addSeparator()

        act_compare = None
        if self._mode == "polar2d":
            act_compare = menu.addAction("Comparar bandas…")
            menu.addSeparator()

        act_properties = menu.addAction("Propiedades…")
        act_auto = menu.addAction("Autoescala")
        act_auto.setEnabled(self._min_db is not None or self._max_db is not None)
        menu.addSeparator()
        act_save = menu.addAction("Guardar imagen…")

        action = menu.exec(self.view.mapToGlobal(pos))
        try:
            if action == act_zoom:
                self.zoom_requested.emit(self._mode)
            elif action == act_properties:
                self.properties_requested.emit()
            elif action == act_auto:
                self._reset_scale()
            elif action == act_save:
                self.save_requested.emit(self._mode)
            elif action == act_iso:
                self.view.set_camera_view('iso')
            elif action == act_default:
                self.view.set_camera_view('default')
            elif action == act_top:
                self.view.set_camera_view('top')
            elif action == act_bottom:
                self.view.set_camera_view('bottom')
            elif action == act_front:
                self.view.set_camera_view('front')
            elif action == act_back:
                self.view.set_camera_view('back')
            elif action == act_compare:
                self._open_tab = "Comparación"
                self.properties_requested.emit()
        except Exception:
            import traceback
            self.log.emit(f"[ERROR] Menú contextual ({self._mode}):\n{traceback.format_exc()}")

    @staticmethod
    def _to_qcolor(color_str: str) -> QColor:
        """
        QColor(str) sólo entiende nombres SVG y hex (#RRGGBB/#AARRGGBB) — NO
        el formato CSS rgba(r,g,b,a) que usan varios colores de tema
        (ej. _RING_LINE = "rgba(255,255,255,0.12)"), y devuelve un color
        inválido en ese caso, rompiendo el selector de color. Este helper
        also soporta rgba()/rgb().
        """
        c = QColor(color_str)
        if c.isValid():
            return c
        m = re.match(
            r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)',
            color_str,
        )
        if m:
            r_, g_, b_ = int(m.group(1)), int(m.group(2)), int(m.group(3))
            a_ = round(float(m.group(4)) * 255) if m.group(4) else 255
            return QColor(r_, g_, b_, a_)
        return QColor("white")

    def _make_color_button(self, dlg: QWidget, initial_color: str) -> QPushButton:
        """Botón cuadrado que abre un QColorDialog y guarda el color elegido
        en su atributo .color_hex — reutilizado en todas las secciones del
        diálogo de Propiedades."""
        btn = QPushButton()
        btn.setAutoDefault(False)     # Enter en un campo del diálogo no debe 'apretar' el botón de color
        btn.setFixedSize(28, 20)
        btn.color_hex = self._to_qcolor(initial_color).name()
        btn.setStyleSheet(f"background:{btn.color_hex};border:1px solid #555;")

        def _pick(checked=False, _btn=btn):
            c = QColorDialog.getColor(self._to_qcolor(_btn.color_hex), dlg)
            if c.isValid():
                _btn.color_hex = c.name()
                _btn.setStyleSheet(f"background:{_btn.color_hex};border:1px solid #555;")
                if getattr(_btn, 'on_change', None):
                    _btn.on_change()
        btn.clicked.connect(_pick)
        return btn

    def build_properties_widget(self, close_cb) -> QWidget:
        """
        Contenido de Propiedades del gráfico (dentro del modal de
        TabDirectividad._show_properties_panel). Cada cambio se aplica solo,
        con un pequeño retardo, sin botón "Aplicar". Las secciones que aplican dependen del tipo de vista
        (self._mode): escala, fondo, ejes/grilla (3D/Esfera), ejes/traza
        (Polar 2D) o barras/grilla (Espectro).

        close_cb : callback sin argumentos, invocado al presionar "Cerrar"
                   (típicamente oculta el QDockWidget contenedor).
        """
        from plot import balloon as _balloon_mod

        # Una pestaña por sección (Escala, Ejes…): así todo entra sin deslizar.
        dlg = tabs = QTabWidget()
        tabs.tabBar().setUsesScrollButtons(False)

        class _Tabs:                       # cada group box que se "agrega" pasa a ser una pestaña
            def addWidget(self, box):
                tabs.addTab(box, box.title())
                box.setTitle("")
                box.setObjectName("prop_page")
            def addStretch(self, *_):
                pass

        outer = _Tabs()
        fields: dict = {}

        if True:                       # todos los gráficos tienen escala
            box = QGroupBox("Escala")
            form = QFormLayout(box)
            le_min = QLineEdit("" if self._min_db is None else str(self._min_db))
            le_min.setFixedWidth(70)
            le_min.setPlaceholderText("auto")
            le_min.setToolTip("Límite inferior del rango de dB mostrado. Vacío = automático (recomendado para empezar).\nEjemplo: -30")
            le_max = QLineEdit("" if self._max_db is None else str(self._max_db))
            le_max.setFixedWidth(70)
            le_max.setPlaceholderText("auto")
            le_max.setToolTip("Límite superior del rango de dB mostrado. Vacío = automático (recomendado para empezar).\nEjemplo: 0")
            form.addRow("Min (dB):", le_min)
            form.addRow("Max (dB):", le_max)
            fields['min_db'], fields['max_db'] = le_min, le_max
            outer.addWidget(box)

        if self._mode in ("3d", "sphere"):
            box_ax = QGroupBox("Ejes / grilla")
            form_ax = QFormLayout(box_ax)
            btn_grid = self._make_color_button(dlg, self._axis_color or _balloon_mod._GRID_COL)
            btn_grid.setToolTip("Color de la grilla circular de fondo (las líneas guía de la esfera). Click para elegir.")
            form_ax.addRow("Color de grilla:", btn_grid)
            spin_grid_w = _NumEdit()
            spin_grid_w.setRange(0.5, 8.0); spin_grid_w.setSingleStep(0.5)
            spin_grid_w.setValue(self._axis_width)
            spin_grid_w.setToolTip("Grosor de las líneas de la grilla. Valor típico: 1 a 2. Por defecto: 1.")
            form_ax.addRow("Grosor de grilla:", spin_grid_w)
            spin_label = _NumEdit()
            spin_label.setRange(6, 24); spin_label.setSingleStep(1)
            spin_label.setValue(self._style.get('axis_label_size', FONT_SIZE))
            spin_label.setToolTip("Tamaño de las letras X/Y/Z. Valor típico: 10 a 14. Por defecto: 12.")
            form_ax.addRow("Tamaño etiquetas X/Y/Z:", spin_label)
            spin_axis_w = _NumEdit()
            spin_axis_w.setRange(0.5, 8.0); spin_axis_w.setSingleStep(0.5)
            spin_axis_w.setValue(self._style.get('axis_line_width', 3))
            spin_axis_w.setToolTip("Grosor de las líneas de los ejes X/Y/Z. Valor típico: 2 a 4. Por defecto: 3.")
            form_ax.addRow("Grosor líneas X/Y/Z:", spin_axis_w)
            if self._mode == "3d":
                chk_plane = QCheckBox("Mostrar plano translúcido de referencia")
                chk_plane.setChecked(bool(self._style.get('show_ref_plane', True)))
                chk_plane.setToolTip(
                    "El plano chato que marca la altura de la elevación elegida en el grupo "
                    "'Corte (Superficie 3D)' de la barra izquierda. Sólo se ve si ahí se activó "
                    "'Intersectar'; esto lo saca sin desactivar la curva de corte."
                )
                form_ax.addRow(chk_plane)
                chk_grid = QCheckBox("Mostrar grilla hemisférica")
                chk_grid.setChecked(bool(self._style.get('show_hemisphere_grid', True)))
                chk_grid.setToolTip("Los círculos de latitud/longitud de referencia alrededor de la superficie.")
                form_ax.addRow(chk_grid)
                fields['show_ref_plane']       = chk_plane
                fields['show_hemisphere_grid'] = chk_grid

            fields['grid_color']     = btn_grid
            fields['grid_width']     = spin_grid_w
            fields['axis_label_size'] = spin_label
            fields['axis_line_width'] = spin_axis_w
            outer.addWidget(box_ax)

        if self._mode == "3d":
            box_calc = QGroupBox("Método de cálculo")
            form_calc = QFormLayout(box_calc)
            combo_geom = QComboBox()
            combo_geom.addItem("Radial al origen", "origin")
            combo_geom.addItem("Radial al eje Z", "zaxis")
            combo_geom.setCurrentIndex(max(0, combo_geom.findData(self._style.get('geometry_mode', 'origin'))))
            combo_geom.setToolTip(
                "Cómo se construye la superficie a partir del nivel medido.\n"
                "Radial al origen: el nivel escala todo el vector desde el centro (balloon clásico).\n"
                "Radial al eje Z: el nivel sólo escala la parte horizontal; la altura depende nada "
                "más del ángulo de elevación — un corte horizontal coincide exacto con una elevación."
            )
            form_calc.addRow("Construcción:", combo_geom)
            fields['geometry_mode'] = combo_geom
            outer.addWidget(box_calc)

        elif self._mode == "polar2d":
            box_ax = QGroupBox("Ejes / traza")
            form_ax = QFormLayout(box_ax)
            spin_tick = _NumEdit()
            spin_tick.setRange(6, 30); spin_tick.setSingleStep(1)
            spin_tick.setValue(self._tick_font_size)
            spin_tick.setToolTip("Tamaño de los números de ángulo (0°, 45°, 90°...). Valor típico: 10 a 14. Por defecto: 12.")
            form_ax.addRow("Tamaño de números (grados):", spin_tick)
            spin_ring_font = _NumEdit()
            spin_ring_font.setRange(6, 30); spin_ring_font.setSingleStep(1)
            spin_ring_font.setValue(self._style.get('ring_font_size', FONT_SIZE))
            spin_ring_font.setToolTip("Tamaño de los números de dB de los anillos (-10, -5, 0...). Valor típico: 8 a 12. Por defecto: 9.")
            form_ax.addRow("Tamaño de números (dB):", spin_ring_font)
            spin_ring_step = _NumEdit()
            spin_ring_step.setRange(1, 20); spin_ring_step.setSingleStep(1)
            spin_ring_step.setValue(self._style.get('ring_step', 5.0))
            spin_ring_step.setToolTip("Cada cuántos dB se dibuja un anillo de referencia. Valor típico: 5 (default) o 3 si querés más detalle.")
            form_ax.addRow("Paso entre anillos (dB):", spin_ring_step)
            spin_ring_angle = _NumEdit()
            spin_ring_angle.setRange(0, 360); spin_ring_angle.setSingleStep(5)
            spin_ring_angle.setValue(self._style.get('ring_label_angle', 92))
            spin_ring_angle.setToolTip(
                "Ángulo donde aparecen los números de dB de los anillos (0°=derecha,\n"
                "90°=arriba, 180°=izquierda, 270°=abajo). Por defecto: 92° (casi arriba).\n"
                "Cambialo si los números tapan la curva medida en algún punto."
            )
            form_ax.addRow("Ángulo de etiquetas de dB (°):", spin_ring_angle)
            combo_ring_pos = QComboBox()
            combo_ring_pos.setMaximumWidth(120)
            combo_ring_pos.addItems(['center', 'left', 'right'])
            combo_ring_pos.setCurrentText(self._style.get('ring_label_pos', 'center'))
            combo_ring_pos.setToolTip(
                "Posición del número respecto de la línea radial donde está apoyado.\n"
                "center: sobre la línea (default).\n"
                "left / right: corrido a un costado, útil si el número tapa\n"
                "la línea radial o la curva medida."
            )
            form_ax.addRow("Posición de etiquetas de dB:", combo_ring_pos)
            spin_line_w = _NumEdit()
            spin_line_w.setRange(0.5, 8.0); spin_line_w.setSingleStep(0.5)
            spin_line_w.setValue(self._style.get('line_width', 2.5))
            spin_line_w.setToolTip("Grosor de la curva del patrón (sólo aplica con una banda a la vez). Valor típico: 2 a 3. Por defecto: 2.5.")
            form_ax.addRow("Grosor de traza (banda única):", spin_line_w)
            spin_legend = _NumEdit()
            spin_legend.setRange(6, 30); spin_legend.setSingleStep(1)
            spin_legend.setValue(self._style.get('legend_font_size', FONT_SIZE))
            spin_legend.setToolTip("Tamaño de la leyenda cuando comparás varias bandas superpuestas. Valor típico: 11 a 14. Por defecto: 12.")
            form_ax.addRow("Tamaño de leyenda (multibanda):", spin_legend)
            fields['tick_font_size']    = spin_tick
            fields['ring_font_size']    = spin_ring_font
            fields['ring_step']         = spin_ring_step
            fields['ring_label_angle']  = spin_ring_angle
            fields['ring_label_pos']    = combo_ring_pos
            fields['line_width']        = spin_line_w
            fields['legend_font_size']  = spin_legend
            outer.addWidget(box_ax)

            box_rg = QGroupBox("Anillos y radios")
            form_rg = QFormLayout(box_rg)
            btn_ring = self._make_color_button(dlg, self._style.get('ring_color') or "#000000")
            btn_ring.setToolTip("Color de los anillos de dB. No cambia el color de los números.")
            form_rg.addRow("Anillos — color:", btn_ring)
            spin_ring_w = _NumEdit()
            spin_ring_w.setRange(0.25, 8.0)
            spin_ring_w.setValue(self._style.get('ring_width', 1))
            form_rg.addRow("Anillos — grosor:", spin_ring_w)
            combo_ring_dash = QComboBox()
            combo_ring_dash.addItems(_DASH_STYLES)
            combo_ring_dash.setCurrentText(self._style.get('ring_dash', 'dot'))
            form_rg.addRow("Anillos — tipo de línea:", combo_ring_dash)
            spin_spoke_step = _NumEdit()
            spin_spoke_step.setRange(0, 180)
            spin_spoke_step.setValue(self._style.get('spoke_step', 30 if self._style.get('show_spokes', True) else 0))
            spin_spoke_step.setToolTip("Cada cuántos grados va una línea radial. 0 = sin líneas radiales.")
            form_rg.addRow("Líneas radiales cada (°):", spin_spoke_step)
            btn_spoke = self._make_color_button(dlg, self._style.get('spoke_color') or self._style.get('ring_color') or "#000000")
            form_rg.addRow("Radios — color:", btn_spoke)
            spin_spoke_w = _NumEdit()
            spin_spoke_w.setRange(0.25, 8.0)
            spin_spoke_w.setValue(self._style.get('spoke_width', 1))
            form_rg.addRow("Radios — grosor:", spin_spoke_w)
            combo_spoke_dash = QComboBox()
            combo_spoke_dash.addItems(_DASH_STYLES)
            combo_spoke_dash.setCurrentText(self._style.get('spoke_dash', 'dot'))
            form_rg.addRow("Radios — tipo de línea:", combo_spoke_dash)
            fields['ring_color'], fields['ring_width'], fields['ring_dash'] = btn_ring, spin_ring_w, combo_ring_dash
            fields['spoke_step'], fields['spoke_color'] = spin_spoke_step, btn_spoke
            fields['spoke_width'], fields['spoke_dash'] = spin_spoke_w, combo_spoke_dash
            outer.addWidget(box_rg)

            fields['_compare'] = _CompareEditor(self, dlg)
            outer.addWidget(fields['_compare'])

        elif self._mode == "spectrum":
            box_sp = QGroupBox("Barras")
            form_sp = QFormLayout(box_sp)
            btn_bar = self._make_color_button(dlg, self._style.get('bar_color') or "#146B64")
            btn_bar.setToolTip("Color de las barras cuando el modo de vista está en 'Global'. No aplica al modo 'Por toma' (usa un color distinto por azimuth).")
            form_sp.addRow("Color de barras (modo Global):", btn_bar)
            btn_err = self._make_color_button(dlg, self._style.get('err_color') or "#C4791F")
            btn_err.setToolTip("Color del bigote de dispersión (±σ entre tomas). Sólo en modo Global.")
            form_sp.addRow("Color del bigote de dispersión:", btn_err)
            spin_err_w = _NumEdit()
            spin_err_w.setRange(0.5, 8.0)
            spin_err_w.setValue(self._style.get('err_width', 2))
            form_sp.addRow("Grosor del bigote:", spin_err_w)
            fields['bar_color'], fields['err_color'], fields['err_width'] = btn_bar, btn_err, spin_err_w
            outer.addWidget(box_sp)

            box_ex = QGroupBox("Ejes")
            form_ex = QFormLayout(box_ex)
            spin_ax_f = _NumEdit()
            spin_ax_f.setRange(6, 30)
            spin_ax_f.setValue(self._style.get('axis_font_size', FONT_SIZE))
            form_ex.addRow("Tamaño de números de los ejes:", spin_ax_f)
            spin_lb_f = _NumEdit()
            spin_lb_f.setRange(6, 30)
            spin_lb_f.setValue(self._style.get('label_font_size', FONT_SIZE))
            form_ex.addRow("Tamaño de títulos de los ejes:", spin_lb_f)
            fields['axis_font_size'], fields['label_font_size'] = spin_ax_f, spin_lb_f
            outer.addWidget(box_ex)

            box_gr = QGroupBox("Grilla")
            form_gr = QFormLayout(box_gr)
            combo_grid = QComboBox()
            for label, val in (("Horizontales", "h"), ("Verticales", "v"), ("Horizontales y verticales", "both"), ("Sin grilla", "none")):
                combo_grid.addItem(label, val)
            combo_grid.setCurrentIndex(max(0, combo_grid.findData(self._style.get('grid_mode', 'h'))))
            form_gr.addRow("Líneas de grilla:", combo_grid)
            spin_gr_a = _NumEdit()
            spin_gr_a.setRange(0.0, 1.0)
            spin_gr_a.setValue(self._style.get('grid_alpha', 0.15))
            spin_gr_a.setToolTip("Intensidad de la grilla: 0 = invisible, 1 = negra. Por defecto 0.15.")
            form_gr.addRow("Intensidad (0–1):", spin_gr_a)
            spin_gr_s = _NumEdit()
            spin_gr_s.setRange(0, 200)
            spin_gr_s.setValue(self._style.get('grid_step', 0))
            spin_gr_s.setToolTip("Cada cuántos dB va una línea horizontal. 0 = automático.")
            form_gr.addRow("Paso (dB, 0 = automático):", spin_gr_s)
            fields['grid_mode'], fields['grid_alpha'], fields['grid_step'] = combo_grid, spin_gr_a, spin_gr_s
            outer.addWidget(box_gr)

        def _apply():
            try:
                self._min_db = float(fields['min_db'].text()) if fields['min_db'].text().strip() else None
                self._max_db = float(fields['max_db'].text()) if fields['max_db'].text().strip() else None
            except ValueError:
                pass

            new_style = dict(self._style)

            if self._mode in ("3d", "sphere"):
                self._axis_color = fields['grid_color'].color_hex
                self._axis_width = fields['grid_width'].value()
                new_style['axis_label_size'] = fields['axis_label_size'].value()
                new_style['axis_line_width'] = fields['axis_line_width'].value()
                if self._mode == "3d":
                    new_style['show_ref_plane']       = fields['show_ref_plane'].isChecked()
                    new_style['show_hemisphere_grid'] = fields['show_hemisphere_grid'].isChecked()
                    new_style['geometry_mode']        = fields['geometry_mode'].currentData()
            elif self._mode == "polar2d":
                self._tick_font_size = fields['tick_font_size'].value()
                new_style['ring_font_size']    = fields['ring_font_size'].value()
                new_style['ring_step']         = fields['ring_step'].value()
                new_style['ring_label_angle']  = fields['ring_label_angle'].value()
                new_style['ring_label_pos']    = fields['ring_label_pos'].currentText()
                new_style['ring_color']        = fields['ring_color'].color_hex
                new_style['ring_width']        = fields['ring_width'].value()
                new_style['ring_dash']         = fields['ring_dash'].currentText()
                new_style['spoke_step']        = fields['spoke_step'].value()
                new_style['spoke_color']       = fields['spoke_color'].color_hex
                new_style['spoke_width']       = fields['spoke_width'].value()
                new_style['spoke_dash']        = fields['spoke_dash'].currentText()
                sel, styles, legend = fields['_compare'].state()
                self._compare_indices = sel if len(sel) > 1 else None
                self._compare_styles = styles
                new_style['legend_pos'] = legend['pos']
                new_style['show_legend'] = legend['show']
                self.view.set_compare_bands(self._compare_indices)
                self.view.set_compare_styles(self._compare_styles)
                new_style['line_width']        = fields['line_width'].value()
                new_style['legend_font_size']  = fields['legend_font_size'].value()
            elif self._mode == "spectrum":
                new_style['bar_color']  = fields['bar_color'].color_hex
                new_style['err_color']  = fields['err_color'].color_hex
                new_style['err_width']  = fields['err_width'].value()
                new_style['axis_font_size']  = fields['axis_font_size'].value()
                new_style['label_font_size'] = fields['label_font_size'].value()
                new_style['grid_mode']  = fields['grid_mode'].currentData()
                new_style['grid_alpha'] = fields['grid_alpha'].value()
                new_style['grid_step']  = fields['grid_step'].value()

            self._style = new_style
            self.view.set_db_range(self._min_db, self._max_db)
            if self._mode in ("3d", "sphere"):
                self.view.set_axis_style(self._axis_color, self._axis_width)
            elif self._mode == "polar2d":
                self.view.set_tick_font_size(self._tick_font_size)
            self.view.set_style(self._style)
            self.properties_applied.emit()

        outer.addStretch(1)

        # Edición en vivo: cualquier cambio dispara _apply con un retardo (evita re-renderizar por cada tecla)
        timer = QTimer(dlg)
        timer.setSingleShot(True)
        timer.setInterval(400)

        def _safe_apply():
            try:
                _apply()
            except Exception:       # texto a medio escribir, etc.
                pass

        timer.timeout.connect(_safe_apply)
        sched = lambda *_: timer.start()
        for w in fields.values():
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(sched)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(sched)
            elif isinstance(w, QLineEdit):      # incluye _NumEdit
                w.textChanged.connect(sched)
            else:                               # botón de color
                w.on_change = sched

        tabs.flush = lambda: timer.isActive() and (timer.stop(), _safe_apply())   # al cerrar, no perder el último cambio
        return tabs

    def restore_defaults(self):
        """Vuelve el gráfico a la configuración estándar del programa (ver _DEFAULT_*)."""
        self._style          = dict(_DEFAULT_STYLE_BY_MODE.get(self._mode, {}))
        self._min_db         = _DEFAULT_MIN_DB_BY_MODE.get(self._mode)
        self._max_db         = _DEFAULT_MAX_DB_BY_MODE.get(self._mode)
        self._tick_font_size = FONT_SIZE
        self._axis_color     = None
        self._axis_width     = 1
        self.view.set_db_range(self._min_db, self._max_db)
        if self._mode in ("3d", "sphere"):
            self.view.set_axis_style(self._axis_color, self._axis_width)
        elif self._mode == "polar2d":
            self.view.set_tick_font_size(self._tick_font_size)
        self.view.set_style(self._style)
        self.properties_applied.emit()

    def _reset_scale(self):
        self._min_db = None
        self._max_db = None
        self.view.set_db_range(None, None)

    def _snapshot_properties(self) -> dict:
        return dict(
            style=dict(self._style), min_db=self._min_db, max_db=self._max_db,
            tick_font_size=self._tick_font_size,
            axis_color=self._axis_color, axis_width=self._axis_width,
        )

    def _push_undo_snapshot(self):
        """Guarda el estado ANTES de aplicar un cambio de Propiedades, para
        poder deshacerlo con Ctrl+Z (ver TabDirectividad._undo_properties)."""
        self._props_undo_stack.append(self._snapshot_properties())
        if len(self._props_undo_stack) > 20:
            self._props_undo_stack.pop(0)

    def undo_properties(self) -> bool:
        """Restaura el snapshot previo al último 'Aplicar' de Propiedades.
        Devuelve False si no hay nada para deshacer."""
        if not self._props_undo_stack:
            return False
        self._apply_snapshot(self._props_undo_stack.pop())
        return True

    def _apply_snapshot(self, snap: dict):
        self._style          = dict(snap['style'])
        self._min_db         = snap['min_db']
        self._max_db         = snap['max_db']
        self._tick_font_size = snap['tick_font_size']
        self._axis_color     = snap['axis_color']
        self._axis_width     = snap['axis_width']

        self.view.set_db_range(self._min_db, self._max_db)
        if self._mode in ("3d", "sphere"):
            self.view.set_axis_style(self._axis_color, self._axis_width)
        elif self._mode == "polar2d":
            self.view.set_tick_font_size(self._tick_font_size)
        self.view.set_style(self._style)

    def get_config(self) -> dict:
        """Propiedades del gráfico en forma serializable (para guardar junto con los datos)."""
        c = self._snapshot_properties()
        c['compare_indices'] = [int(i) for i in self._compare_indices] if self._compare_indices else None
        c['compare_styles'] = {str(k): v for k, v in self._compare_styles.items()}
        return c

    def apply_config(self, c: dict):
        self._apply_snapshot(c)
        self._compare_indices = c.get('compare_indices')
        self._compare_styles = {int(k): v for k, v in (c.get('compare_styles') or {}).items()}
        self.view.set_compare_bands(self._compare_indices)
        self.view.set_compare_styles(self._compare_styles)

    def set_data(self, **kwargs):
        self.view.set_data(**kwargs)

    def set_band(self, index: int):
        self.view.set_band(index)

    def set_colorscale(self, name: str):
        self.view.set_colorscale(name)

    def set_el_index(self, idx):
        self.view.set_el_index(idx)

    def set_plane(self, plane: str):
        self.view.set_plane(plane)

    def set_show_info(self, show: bool):
        self.view.set_show_info(show)

    def export_image(self, path: str, dpi: int = 300, fmt: str = 'png', on_done=None):
        self.view.export_image(path, dpi=dpi, fmt=fmt, on_done=on_done)      # el tamaño sale de Opciones ▸ Imágenes


# ─────────────────────────────────────────────────────────────────────────────

class TabDirectividad(QWidget):
    log      = pyqtSignal(str)
    computed = pyqtSignal(object, str)  # (thetas_np, status_text)
    compute_finished = pyqtSignal()     # terminó un cálculo pedido con 'Calcular' (no al cargar datos)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma             = None
        self._worker: Worker | None = None
        self._full_levels    = None
        self._full_azimuths  = None
        self._full_thetas    = None
        self._full_bands     = None
        self._raw_ref_spl    = None
        self._eq_ref_spl     = None
        self._current_el_idx  = None
        self._plane            = "XY"
        self._show_info        = False
        self._current_band_idx = 0
        self._npz: dict | None = None   # resultados cargados de un .npz (sin MicArray): {nota: {...}}
        self._unit = "dB SPL"          # 'dBFS' si se calculó sin calibrar

        # Estado de controles del ribbon — actualizados por apply_display_params()
        self._hz_min      = 200.0
        self._hz_max      = 8000.0
        self._sym         = "none"
        self._nota        = "Todo el audio"
        self._spec_data   = 0       # 0=raw, 1=eq
        self._spec_global = True
        self._view_checks = {
            "3d": True, "sphere": True, "polar2d": True, "spectrum": True
        }

        self._build_ui()
        from ui.export_utils import get_smoothing_settings
        self.apply_smoothing_settings(get_smoothing_settings())   # última config guardada (Herramientas ▸ Suavizado…)

    def apply_smoothing_settings(self, values: dict):
        """Una sola configuración de suavizado para Polar 2D, Superficie 3D y Esfera (Herramientas
        ▸ Suavizado…, ver ui/options_dialogs.py::SmoothingOptionsDialog) — reemplaza los paneles
        de Suavizado/Interpolación que antes tenía cada Propiedades por separado, duplicados y
        potencialmente desalineados entre sí."""
        common = {k: values[k] for k in ('smoothing_method', 'smoothing_window', 'interp_deg')}
        for mode in ('3d', 'sphere'):
            sec = self._sections[mode]
            sec._style.update(common, smoothing=values['spline_factor'])
            sec.view.set_style(sec._style)
        sec = self._sections['polar2d']
        sec._style.update(common, interp_kind=values['interp_kind'])
        sec.view.set_style(sec._style)

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_right_panel(), 1)

    def _make_right_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        self._sections: dict[str, _ViewSection] = {
            "3d":       _ViewSection("Superficie 3D", "3d"),
            "sphere":   _ViewSection("Esfera",        "sphere"),
            "polar2d":  _ViewSection("Polar 2D",      "polar2d"),
            "spectrum": _ViewSection("Espectro",      "spectrum"),
        }
        self._section_titles = {
            "3d": "Superficie 3D", "sphere": "Esfera",
            "polar2d": "Polar 2D", "spectrum": "Espectro",
        }
        self._last_props_mode: str | None = None
        for mode, sec in self._sections.items():
            sec.log.connect(self.log)
            sec.save_requested.connect(self._save_section)
            sec.zoom_requested.connect(self.toggle_zoom)
            sec.properties_requested.connect(
                lambda m=mode: self._show_properties_panel(m))
            sec.properties_applied.connect(
                lambda m=mode: setattr(self, '_last_props_mode', m))

        # Ctrl+Z deshace el último "Aplicar" de Propiedades (cualquier gráfico).
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo_properties)

        # Grilla 2×2 fija (como VituixCAD): los 4 gráficos siempre visibles, mismas proporciones.
        # Con click derecho ▸ "Ver en grande" uno ocupa toda el área (ver toggle_zoom).
        self._grid_host = QWidget()
        grid = self._grid = QGridLayout(self._grid_host)
        self._cell_pos = {}
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self._cells: dict[str, QWidget] = {}
        self._zoomed: str | None = None
        for mode, row, col in (("polar2d", 0, 0), ("spectrum", 0, 1), ("3d", 1, 0), ("sphere", 1, 1)):
            cell = QWidget()
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(0)
            hdr = QLabel(self._section_titles[mode])
            hdr.setObjectName("plot_title")
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cv.addWidget(hdr)
            cv.addWidget(self._sections[mode], 1)
            grid.addWidget(cell, row, col)
            self._cell_pos[mode] = (row, col)
            self._cells[mode] = cell
        for k in (0, 1):
            grid.setRowStretch(k, 1)
            grid.setColumnStretch(k, 1)

        lay.addWidget(self._grid_host, 1)

        self.band_selector = BandSelectorWidget()
        self.band_selector.band_changed.connect(self._on_band_changed)
        lay.addWidget(self.band_selector)

        return w

    def toggle_zoom(self, mode: str):
        """'Ver en grande': el gráfico elegido ocupa toda el área; repetir para volver a los 4.
        Los tamaños de fuente son px literales, así que no cambian al agrandar."""
        z = None if self._zoomed == mode else mode
        self._zoomed = z
        for m, cell in self._cells.items():
            cell.setVisible(z is None or m == z)
        r, c = self._cell_pos.get(z, (None, None))
        for k in (0, 1):                # sólo la fila/columna del gráfico ampliado se estira
            self._grid.setRowStretch(k, 1 if z is None or k == r else 0)
            self._grid.setColumnStretch(k, 1 if z is None or k == c else 0)
        for m, sec in self._sections.items():
            sec.set_zoomed(m == z)
        self.band_selector.setVisible(z != "spectrum")
        if z is None:                      # los ocultos no siguieron los cambios de banda
            for sec in self._sections.values():
                sec.set_band(self._current_band_idx)

    # ── Slots internos ────────────────────────────────────────────────────

    def _on_band_changed(self, index: int, hz: float):
        self._current_band_idx = index
        for sec in self._sections.values():
            if sec.isVisible():
                sec.set_band(index)

    def _run_compute(self, bands: str, ref_az: int, ref_th: int):
        ma = self._get_current_ma()
        ma.compute_directivity(
            bands          = bands,
            ref_azimuth    = ref_az,
            ref_theta_plot = ref_th,
        )
        return ma

    def _on_compute_done(self, ma):
        nota = self._nota
        if nota != "Todo el audio" and self._ma and self._ma.notes:
            self._ma.notes[nota] = ma
        else:
            self._ma = ma
        self._show_results(self._get_current_ma())
        if self._full_levels is not None and self._full_bands is not None:
            status = (
                f"Dir. calculada — {self._full_levels.shape}  |  "
                f"{self._full_bands[0]:.0f}–{self._full_bands[-1]:.0f} Hz"
            )
            self.computed.emit(self._full_thetas, status)
        self.log.emit("[Directividad] Cómputo completado.")

    def _show_results(self, ma):
        if ma.dir_levels is None:
            return
        self._unit = "dB SPL" if ma._is_spl else "dBFS"
        thetas_num = [t for t in ma.thetas if t != 'ref']
        theta_idx  = [ma.thetas.index(t) for t in thetas_num]

        # Aplicar rango de frecuencias definido por el usuario al momento del cómputo
        band_mask = (ma.dir_freqs >= self._hz_min) & (ma.dir_freqs <= self._hz_max)
        if not band_mask.any():
            band_mask = np.ones(len(ma.dir_freqs), dtype=bool)

        self._full_levels   = ma.dir_levels[:, theta_idx, :][:, :, band_mask]
        self._full_azimuths = np.array(ma.angles,  dtype=np.float32)
        self._full_thetas   = np.array(thetas_num, dtype=np.float32)
        self._full_bands    = ma.dir_freqs[band_mask].astype(np.float32)
        self._current_band_idx = 0  # reset al nuevo rango computado

        if ('ref' in ma.thetas
                and ma.dir_ref_spl is not None
                and ma.dir_delta    is not None):
            i_ref = ma.thetas.index('ref')
            base  = (ma.dir_levels[0, i_ref, :] + ma.dir_ref_spl)[band_mask].astype(np.float32)
            self._raw_ref_spl = (base[np.newaxis, :] - ma.dir_delta[:, band_mask]).astype(np.float32)
            self._eq_ref_spl  = base
        elif ma.dir_ref_spl is not None:
            n_az = len(ma.angles)
            self._raw_ref_spl = np.tile(ma.dir_ref_spl[band_mask], (n_az, 1)).astype(np.float32)
            self._eq_ref_spl  = ma.dir_ref_spl[band_mask].astype(np.float32)
        else:
            self._raw_ref_spl = None
            self._eq_ref_spl  = None

        self._refresh_display()

    def _refresh_display(self):
        if self._full_levels is None:
            return

        mask = (self._full_bands >= self._hz_min) & (self._full_bands <= self._hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)

        f_levels = self._full_levels[:, :, mask]
        f_bands  = self._full_bands[mask]

        if self._raw_ref_spl is not None:
            if self._spec_data == 0:
                f_ref = self._raw_ref_spl[:, mask]
            else:
                n_az  = self._raw_ref_spl.shape[0]
                f_ref = np.tile(self._eq_ref_spl[mask], (n_az, 1))
        else:
            f_ref = None

        self.band_selector.set_bands(f_bands)
        self._sections['spectrum'].view.set_unit(self._unit)
        # Clamp el índice de banda al nuevo tamaño de f_bands
        safe_band = min(self._current_band_idx, max(0, len(f_bands) - 1))

        kwargs = dict(
            levels        = f_levels,
            azimuths      = self._full_azimuths,
            elevations    = self._full_thetas,
            bands         = f_bands,
            band_index    = safe_band,
            ref_spectrum  = f_ref,
            spec_global   = self._spec_global,
            symmetry_type = self._sym,
        )
        for mode, sec in self._sections.items():
            # No se filtra por isVisible(): con el ribbon HTML el cambio de
            # tab es asincrónico (round-trip por JS/QWebChannel), así que en
            # el momento de este refresh la sección puede aún reportarse
            # como no visible aunque el tab ya esté por mostrarse. El
            # QWebEngineView renderiza igual estando oculto, sin costo real.
            sec.set_data(**kwargs)
            if self._current_el_idx is not None:
                sec.set_el_index(self._current_el_idx)
            sec.set_plane(self._plane)
            sec.set_show_info(self._show_info)

    def _update_section(self, mode: str):
        if self._full_levels is None:
            return
        mask = (self._full_bands >= self._hz_min) & (self._full_bands <= self._hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)

        f_levels = self._full_levels[:, :, mask]
        f_bands  = self._full_bands[mask]

        if self._raw_ref_spl is not None:
            f_ref = (self._raw_ref_spl[:, mask] if self._spec_data == 0
                     else np.tile(self._eq_ref_spl[mask],
                                  (self._raw_ref_spl.shape[0], 1)))
        else:
            f_ref = None

        safe_band = min(self._current_band_idx, max(0, len(f_bands) - 1))
        sec = self._sections[mode]
        sec.set_data(
            levels        = f_levels,
            azimuths      = self._full_azimuths,
            elevations    = self._full_thetas,
            bands         = f_bands,
            band_index    = safe_band,
            ref_spectrum  = f_ref,
            spec_global   = self._spec_global,
            symmetry_type = self._sym,
        )
        if self._current_el_idx is not None:
            sec.set_el_index(self._current_el_idx)
        sec.set_plane(self._plane)
        sec.set_show_info(self._show_info)

    def _undo_properties(self):
        """Ctrl+Z: deshace el último cambio de Propiedades aplicado, en
        cualquiera de los 4 gráficos (el último que se tocó)."""
        mode = self._last_props_mode
        if mode is None or mode not in self._sections:
            return
        if self._sections[mode].undo_properties():
            self.log.emit(f"[Directividad] Deshecho último cambio de Propiedades ({self._section_titles[mode]}).")

    def _show_properties_panel(self, mode: str):
        """Propiedades del gráfico en un modal: los cambios se ven en vivo (sin 'Aplicar') y hay
        'Restaurar por defecto'. Se ubica a la derecha para dejar a la vista los gráficos."""
        sec = self._sections[mode]
        sec._push_undo_snapshot()          # Ctrl+Z vuelve al estado previo a esta edición
        win = self.window()
        dlg = QDialog(win)
        dlg.setWindowTitle(f"Propiedades — {self._section_titles[mode]}")
        dlg.setMinimumWidth(430)

        lay = QVBoxLayout(dlg)
        holder = QVBoxLayout()
        lay.addLayout(holder, 1)
        current = {}

        def build():
            while holder.count():
                item = holder.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            current['w'] = sec.build_properties_widget(dlg.close)
            holder.addWidget(current['w'])

        build()
        if sec._open_tab:
            tw = current['w']
            for k in range(tw.count()):
                if tw.tabText(k) == sec._open_tab:
                    tw.setCurrentIndex(k)
            sec._open_tab = None
        row = QHBoxLayout()
        btn_reset = QPushButton("Restaurar por defecto")
        btn_reset.setAutoDefault(False)
        btn_reset.setToolTip("Vuelve este gráfico a la configuración estándar del programa")
        btn_reset.clicked.connect(lambda: (sec.restore_defaults(), build()))
        btn_close = QPushButton("Cerrar")
        btn_close.setAutoDefault(False)     # Enter mientras se escribe no cierra el diálogo
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_reset)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.finished.connect(lambda _=0: current['w'].flush())
        dlg.adjustSize()
        g = win.geometry()
        dlg.move(g.right() - dlg.width() - 24, g.top() + 60)
        dlg.exec()

    def _get_current_ma(self):
        if self._nota != "Todo el audio" and self._ma and self._ma.notes:
            return self._ma.notes.get(self._nota, self._ma)
        return self._ma

    def _on_error(self, msg: str):
        self.log.emit(f"[ERROR]\n{msg}")

    # ── API pública ───────────────────────────────────────────────────────

    def get_ma(self):
        """MicArray con la directividad calculada (y .notes poblado si se
        computó por nota) — puede ser un objeto distinto al que se pasó a
        set_ma() la primera vez, ver _on_compute_done()."""
        return self._ma

    def set_ma(self, ma):
        self._ma = ma
        self._npz = None
        if ma.dir_levels is not None:
            self._show_results(ma)
            status = (
                f"Dir. disponible — {ma.dir_levels.shape}  |  "
                f"{ma.dir_freqs[0]:.0f}–{ma.dir_freqs[-1]:.0f} Hz"
            )
            self.computed.emit(
                np.array([t for t in ma.thetas if t != 'ref'], dtype=np.float32),
                status,
            )

    def compute(self, bands: str, hz_min: float, hz_max: float,
                ref_az: int, ref_th: int):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self._hz_min = hz_min
        self._hz_max = hz_max
        self.log.emit("[Directividad] Calculando…")
        self._worker = Worker(
            lambda: self._run_compute(bands, ref_az, ref_th)
        )
        self._worker.label = "Calculando directividad…"
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_compute_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def compute_all(self, bands: str, hz_min: float, hz_max: float,
                    ref_az: int, ref_th: int):
        """Calcula directividad para todo el audio y todas las notas en batch."""
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self._hz_min = hz_min
        self._hz_max = hz_max

        n_notes = len(self._ma.notes) if self._ma.notes else 0
        n_total = 1 + n_notes

        # El progreso se ve en la barra de estado (sin diálogo modal: una ventana extra que aparece y
        # desaparece hacía parpadear la aplicación).
        self._worker = _ComputeAllWorker(self._ma, bands, ref_az, ref_th)
        self._worker.log.connect(self.log)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.error.connect(self._on_error)

        self.log.emit(
            f"[Directividad] Iniciando cómputo — "
            f"1 audio completo + {n_notes} nota(s)…"
        )
        self._worker.start()

    def _on_all_done(self):
        # Mostrar resultados del audio completo por defecto
        self._nota = "Todo el audio"
        self._show_results(self._ma)
        if self._ma.dir_levels is not None:
            status = (
                f"Dir. calculada — {self._ma.dir_levels.shape}  |  "
                f"{self._ma.dir_freqs[0]:.0f}–{self._ma.dir_freqs[-1]:.0f} Hz"
                + ("" if self._ma._is_spl else "  |  SIN CALIBRAR (dBFS)")
            )
            self.computed.emit(
                np.array([t for t in self._ma.thetas if t != 'ref'],
                         dtype=np.float32),
                status,
            )
        self.log.emit("[Directividad] Todas las configuraciones calculadas.")
        self.compute_finished.emit()

    def load_from_npz(self, data: dict) -> list:
        """Carga resultados desde el dict devuelto por data_store.load_results().
        Guarda también los datos por nota para poder cambiar de nota sin MicArray.
        Devuelve los nombres de nota disponibles."""
        f32 = lambda k: data[k].astype(np.float32) if k in data else None
        self._npz = {"Todo el audio": dict(levels=f32('dir_levels'), spl_ref=f32('spl_ref'),
                                            spl_ref_az=f32('spl_ref_per_az'))}
        notes = []
        for key in data:
            if key.startswith('note_') and key.endswith('_dir_levels'):
                name = key[len('note_'):-len('_dir_levels')]
                notes.append(name)
                self._npz[name] = dict(levels=f32(key), spl_ref=f32(f'note_{name}_spl_ref'),
                                       spl_ref_az=f32(f'note_{name}_spl_ref_per_az'))
        self._full_azimuths = data['azimuths'].astype(np.float32)
        self._full_thetas   = data['thetas'].astype(np.float32)
        self._full_bands    = data['dir_freqs'].astype(np.float32)
        self._unit = (data.get('metadata') or {}).get('unit', 'dB SPL')
        self._apply_npz_entry("Todo el audio")
        return notes

    def _apply_npz_entry(self, name: str):
        e = self._npz[name]
        self._full_levels = e['levels']
        self._eq_ref_spl  = e['spl_ref']
        self._raw_ref_spl = e['spl_ref_az']   # None en NPZ antiguos (sin espectro por toma)
        self._refresh_display()

    def get_view_config(self) -> dict:
        """Propiedades de los 4 gráficos + banda activa (se guardan junto con el .npz de directividad)."""
        return {'sections': {m: s.get_config() for m, s in self._sections.items()},
                'band_index': int(self._current_band_idx)}

    def apply_view_config(self, cfg: dict):
        for m, c in (cfg.get('sections') or {}).items():
            if m in self._sections:
                self._sections[m].apply_config(c)
        self._current_band_idx = int(cfg.get('band_index', 0))
        self._refresh_display()
        self.band_selector.set_index(self._current_band_idx)

    def apply_display_params(self, params: dict):
        """
        Actualiza todos los parámetros de visualización con los valores
        devueltos por ribbon.get_dir_display_params().
        """
        old_nota          = self._nota
        self._hz_min      = params.get('hz_min', 315.0)
        self._hz_max      = params.get('hz_max', 10000.0)
        self._sym         = params.get('symmetry', 'none')
        self._nota        = params.get('nota', 'Todo el audio')
        self._spec_data   = params.get('spec_data', 0)
        self._spec_global = params.get('spec_global', True)

        cs = params.get('colorscale', 'Plasma')
        for sec in self._sections.values():
            sec.set_colorscale(cs)

        el_idx = params.get('el_index', None)
        self._current_el_idx = el_idx
        for sec in self._sections.values():
            sec.set_el_index(el_idx)

        self._plane = params.get('plane', 'XY')
        for sec in self._sections.values():
            sec.set_plane(self._plane)

        self._show_info = params.get('show_info', False)
        for sec in self._sections.values():
            sec.set_show_info(self._show_info)

        # Si cambió la nota, recargar datos desde el MA correspondiente
        if self._nota != old_nota:
            if self._npz is not None and self._nota in self._npz:
                self._apply_npz_entry(self._nota)
                return
            current_ma = self._get_current_ma()
            if current_ma is not None and current_ma.dir_levels is not None:
                self._show_results(current_ma)
                return

        self._refresh_display()

    def _save_section(self, mode: str):
        """Guarda la imagen de la sección indicada mediante un diálogo de archivo."""
        if self._full_bands is None:
            self.log.emit("[Dir] Sin datos para guardar.")
            return

        # Primero el DPI (afecta el nombre sugerido del archivo), después dónde guardarlo.
        from ui.export_utils import get_export_defaults
        dpi, ok = QInputDialog.getInt(
            self, "Resolución de exportación", "DPI (el tamaño físico es fijo, ver Opciones ▸ Imágenes):",
            get_export_defaults()[0], 72, 1200, 1
        )
        if not ok:
            return

        mode_label = _MODE_LABELS.get(mode, mode)
        nota = (self._nota
                .replace("Todo el audio", "todo")
                .replace(" ", "_"))

        if mode != "spectrum":
            # La frecuencia del nombre sale del band_selector (lo que el usuario efectivamente
            # ve resaltado), no de self._full_bands[self._current_band_idx]: ese array puede
            # quedar con otro recorte de Rango (Hz) que el que se le pasó al selector la última
            # vez (p. ej. si se cambió el rango sin recalcular), desincronizando los índices y
            # guardando el nombre con una banda distinta a la que se está viendo.
            bi   = min(self._current_band_idx, len(self._full_bands) - 1)
            freq = int(round(self.band_selector.current_band_hz()))
            cmp_idx = [i for i in (self._sections[mode]._compare_indices or []) if i < len(self._full_bands)]
            if mode == "polar2d" and len(cmp_idx) >= 2:      # comparación: todas las bandas superpuestas
                freq = "-".join(str(int(round(float(self._full_bands[i])))) for i in sorted(cmp_idx))
            suggested = f"dir_{mode_label}_{freq}Hz_{nota}_{dpi}dpi.png"
        else:
            suggested = f"dir_{mode_label}_{nota}_{dpi}dpi.png"

        # El SVG del Espectro no es fiel (las barras no se recortan al eje): sólo PNG/JPEG/WEBP
        filters = ("PNG (*.png);;JPEG (*.jpg);;WEBP (*.webp)" if mode == "spectrum"
                   else "PNG (*.png);;SVG vectorial (*.svg);;JPEG (*.jpg);;WEBP (*.webp)")
        from ui.export_utils import get_last_export_dir, set_last_export_dir
        start = str(Path(get_last_export_dir()) / suggested)
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Guardar imagen", start, filters
        )
        if not path:
            return
        set_last_export_dir(str(Path(path).parent))

        fmt_by_filter = {
            "PNG (*.png)": ("png", ".png"),
            "SVG vectorial (*.svg)": ("svg", ".svg"),
            "JPEG (*.jpg)": ("jpeg", ".jpg"),
            "WEBP (*.webp)": ("webp", ".webp"),
        }
        fmt, ext = fmt_by_filter.get(selected_filter, ("png", ".png"))
        if not path.lower().endswith(ext):
            path += ext

        if fmt == 'svg':
            dpi = 300   # vectorial: el DPI no aplica, pero el parámetro existe igual

        self._sections[mode].export_image(path, dpi=dpi, fmt=fmt)

    def export_all_images(self, folder: str, prefix: str, dpi: int = 300, modes=None, fmt: str = 'png'):
        """
        Exporta de una sola vez las imágenes de todas las vistas habilitadas
        (pills del ribbon), para todas las bandas del rango actualmente
        analizado (hz_min/hz_max). El espectro no depende de la banda, así
        que se exporta una única vez.

        modes : vistas a exportar (None = las 4).
        fmt   : 'png' o 'svg'; el SVG (vectorial) sólo aplica a Polar 2D; el resto sale en PNG.

        Nombres: {prefix}_{freq}Hz_{vista}_{dpi}dpi.png  (3D/Esfera/Polar2D)
                 {prefix}_{vista}_{dpi}dpi.png            (Espectro)
        """
        if self._full_bands is None:
            self.log.emit("[Dir] Sin datos para exportar.")
            return

        mask = (self._full_bands >= self._hz_min) & (self._full_bands <= self._hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)
        band_indices = np.nonzero(mask)[0].tolist()

        modes = set(modes) if modes else {"3d", "sphere", "polar2d", "spectrum"}
        if self._zoomed:                       # con un gráfico ampliado los otros están ocultos: sin tamaño real
            self.toggle_zoom(self._zoomed)

        tasks: list[tuple[str, int | None, str]] = []
        for mode in ("3d", "sphere", "polar2d"):
            if mode not in modes:
                continue
            for bi in band_indices:
                freq = int(round(float(self._full_bands[bi])))
                ext = "svg" if (fmt == "svg" and mode == "polar2d") else "png"
                dpi_tag = "" if ext == "svg" else f"_{dpi}dpi"   # vectorial: el DPI no aplica
                tasks.append((mode, bi, f"{prefix}_{freq}Hz_{_MODE_LABELS[mode]}{dpi_tag}.{ext}"))
        if "spectrum" in modes:
            tasks.append(("spectrum", None, f"{prefix}_{_MODE_LABELS['spectrum']}_{dpi}dpi.png"))

        if not tasks:
            self.log.emit("[Dir] No hay gráficos seleccionados para exportar.")
            return

        Path(folder).mkdir(parents=True, exist_ok=True)

        self._export_queue  = tasks
        self._export_folder = folder
        self._export_dpi    = dpi
        self._export_total  = len(tasks)
        self._export_done   = 0

        self._export_dlg = QProgressDialog(
            "Exportando imágenes…", None, 0, self._export_total, self.window())
        self._export_dlg.setWindowTitle("Exportar imágenes")
        self._export_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_dlg.setMinimumDuration(0)
        self._export_dlg.setValue(0)

        self.log.emit(
            f"[Dir] Exportando {self._export_total} imagen(es) a {folder} …"
        )
        self._export_next()

    def _export_next(self):
        if not self._export_queue:
            # Restaurar la banda mostrada a la que tenía el slider antes del lote
            for mode in ("3d", "sphere", "polar2d"):
                if self._view_checks.get(mode, False):
                    self._sections[mode].set_band(self._current_band_idx)
            self._export_dlg.close()
            self.log.emit(
                f"[Dir] Exportación completa — {self._export_done}/{self._export_total} "
                f"imagen(es) en {self._export_folder}."
            )
            return

        mode, band_idx, filename = self._export_queue.pop(0)
        sec  = self._sections[mode]
        path = str(Path(self._export_folder) / filename)
        self._export_dlg.setLabelText(f"Exportando: {filename}")
        file_fmt = 'svg' if filename.endswith('.svg') else 'png'

        def _after_export(ok):
            self._export_done += 1
            self._export_dlg.setValue(self._export_done)
            self._export_next()

        if band_idx is not None:
            sec.set_band(band_idx)
            # El cambio de banda ahora actualiza el gráfico in-place con
            # Plotly.react() (no recarga la página, para conservar cámara/
            # zoom entre bandas — ver balloon_view.py), así que ya no hay un
            # loadFinished al que engancharse. Un margen fijo alcanza porque
            # Plotly.react() es casi instantáneo comparado a una recarga completa.
            QTimer.singleShot(250, lambda: sec.export_image(
                path, dpi=self._export_dpi, fmt=file_fmt, on_done=_after_export))
        else:
            sec.export_image(path, dpi=self._export_dpi, fmt=file_fmt, on_done=_after_export)

    def apply_theme(self, palette: dict):
        """Propaga el cambio de tema a todas las secciones de visualización."""
        for sec in self._sections.values():
            sec.view.apply_theme(palette)
        self.band_selector.apply_theme(palette)
