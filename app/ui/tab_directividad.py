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
    QMainWindow, QDockWidget, QProgressDialog, QFileDialog, QPushButton, QGroupBox,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QComboBox,
    QColorDialog, QInputDialog, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QPoint
from PyQt6.QtGui import QColor, QKeySequence, QShortcut

from core.worker import Worker
from ui.balloon_view import BalloonView
from ui.band_selector import BandSelectorWidget
from plot.balloon import COLORSCALES, _COMPARE_COLORS

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
    "3d":       {"bg_color": "#ffffff", "text_color": "#1a1a1a"},
    "sphere":   {"bg_color": "#ffffff", "text_color": "#1a1a1a"},
    "polar2d":  {
        "bg_color":         "#ffffff",
        "text_color":       "#1a1a1a",
        "ring_color":       "#000000",
        "ring_font_size":   16,
        "ring_step":        5.0,
        "ring_label_angle": 60.0,
        "legend_font_size": 20,
        "line_width":       2.5,
        "show_radial_grid": False,
        "smoothing_method": "savgol",
        "smoothing_window": 3,
        "interp_kind":      "cubic",
        "interp_deg":       2.0,
    },
    "spectrum": {"bg_color": "#ffffff", "text_color": "#1a1a1a"},
}
_DEFAULT_MIN_DB_BY_MODE = {"polar2d": -20.0}
_DEFAULT_MAX_DB_BY_MODE = {"polar2d": 10.0}
_DEFAULT_TICK_FONT_SIZE_BY_MODE = {"polar2d": 16.0}


class _NumEdit(QLineEdit):
    """Campo de texto simple para valores numéricos — reemplaza a
    QDoubleSpinBox en todo el panel de Propiedades (sin flechitas de
    incremento/decremento, sólo texto editable). Réplica el API mínimo
    usado (setRange/setSingleStep/setDecimals/setValue/value) para no
    tener que tocar el resto del código que arma los campos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lo = None
        self._hi = None
        self._decimals = 2
        self.setFixedWidth(70)

    def setRange(self, lo, hi):
        self._lo, self._hi = lo, hi

    def setSingleStep(self, step):
        pass   # sin flechitas, no aplica

    def setDecimals(self, n):
        self._decimals = n

    def setValue(self, v):
        self.setText(str(int(round(v))) if self._decimals == 0 else f"{v:g}")

    def value(self) -> float:
        try:
            v = float(self.text().strip().replace(',', '.'))
        except ValueError:
            v = 0.0
        if self._lo is not None:
            v = max(self._lo, v)
        if self._hi is not None:
            v = min(self._hi, v)
        return v


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
                return len(t)
            def flush(self): pass

        old_out = sys.stdout
        sys.stdout = _Cap(self.log)
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

    def __init__(self, title: str, mode: str, parent=None):
        super().__init__(parent)
        self._mode   = mode
        self._min_db: float | None = _DEFAULT_MIN_DB_BY_MODE.get(mode)
        self._max_db: float | None = _DEFAULT_MAX_DB_BY_MODE.get(mode)
        self._compare_indices: list | None = None   # sólo relevante para polar2d
        self._compare_styles: dict = {}             # {band_index: {'color','width','dash'}}
        self._tick_font_size: float = _DEFAULT_TICK_FONT_SIZE_BY_MODE.get(mode, 11)
        self._axis_color: str | None = None         # color de grilla 3D (3d/sphere), None = tema
        self._axis_width: float = 1                 # grosor de grilla 3D
        self._style: dict = dict(_DEFAULT_STYLE_BY_MODE.get(mode, {}))   # overrides (bg_color, etc.)
        self._props_undo_stack: list[dict] = []   # snapshots previos a cada "Aplicar" (Ctrl+Z)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.view = BalloonView()
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

    def _show_context_menu(self, x: int, y: int):
        pos = QPoint(x, y)
        menu = QMenu(self)

        act_top = act_bottom = act_front = act_back = None
        if self._mode in ("3d", "sphere"):
            view_menu  = menu.addMenu("Vista")
            act_top    = view_menu.addAction("Arriba")
            act_bottom = view_menu.addAction("Abajo")
            act_front  = view_menu.addAction("Frente")
            act_back   = view_menu.addAction("Atrás")
            menu.addSeparator()

        act_compare = act_band_props = None
        if self._mode == "polar2d":
            act_compare = menu.addAction("Comparar bandas…")
            if self._compare_indices:
                act_band_props = menu.addAction("Propiedades de bandas…")
            menu.addSeparator()

        act_properties = menu.addAction("Propiedades…")
        act_auto = menu.addAction("Autoescala")
        act_auto.setEnabled(self._min_db is not None or self._max_db is not None)
        menu.addSeparator()
        act_save = menu.addAction("Guardar imagen…")

        action = menu.exec(self.view._web.mapToGlobal(pos))
        try:
            if action == act_properties:
                self.properties_requested.emit()
            elif action == act_auto:
                self._reset_scale()
            elif action == act_save:
                self.save_requested.emit(self._mode)
            elif action == act_top:
                self.view.set_camera_view('top')
            elif action == act_bottom:
                self.view.set_camera_view('bottom')
            elif action == act_front:
                self.view.set_camera_view('front')
            elif action == act_back:
                self.view.set_camera_view('back')
            elif action == act_compare:
                self._prompt_compare_bands()
            elif action == act_band_props:
                self._prompt_band_properties()
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
        btn.setFixedSize(28, 20)
        btn.color_hex = self._to_qcolor(initial_color).name()
        btn.setStyleSheet(f"background:{btn.color_hex};border:1px solid #555;")

        def _pick(checked=False, _btn=btn):
            c = QColorDialog.getColor(self._to_qcolor(_btn.color_hex), dlg)
            if c.isValid():
                _btn.color_hex = c.name()
                _btn.setStyleSheet(f"background:{_btn.color_hex};border:1px solid #555;")
        btn.clicked.connect(_pick)
        return btn

    def build_properties_widget(self, close_cb) -> QWidget:
        """
        Contenido del panel de Propiedades del gráfico — vive en un
        panel no modal al costado derecho (ver TabDirectividad._show_properties_panel),
        para poder seguir viendo/ajustando el gráfico mientras se cambian
        valores. Las secciones que aplican dependen del tipo de vista
        (self._mode): escala, fondo, ejes/grilla (3D/Esfera), ejes/traza
        (Polar 2D) o barras/grilla (Espectro).

        close_cb : callback sin argumentos, invocado al presionar "Cerrar"
                   (típicamente oculta el QDockWidget contenedor).
        """
        from plot import balloon as _balloon_mod

        dlg = QWidget()   # contenedor de los campos; nombre histórico, ya no es un QDialog
        outer = QVBoxLayout(dlg)
        fields: dict = {}

        if self._mode != "spectrum":
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

        box_bg = QGroupBox("Fondo")
        form_bg = QFormLayout(box_bg)
        default_bg = self._style.get('bg_color') or _balloon_mod._DARK_BG
        btn_bg = self._make_color_button(dlg, default_bg)
        btn_bg.setToolTip("Color de fondo del gráfico. Click para elegir. El color del tema (oscuro/claro) ya viene puesto por defecto.")
        form_bg.addRow("Color de fondo:", btn_bg)
        fields['bg_color'] = btn_bg
        outer.addWidget(box_bg)

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
            spin_label.setValue(self._style.get('axis_label_size', 11))
            spin_label.setToolTip("Tamaño de las letras X/Y/Z. Valor típico: 10 a 14. Por defecto: 11.")
            form_ax.addRow("Tamaño etiquetas X/Y/Z:", spin_label)
            spin_axis_w = _NumEdit()
            spin_axis_w.setRange(0.5, 8.0); spin_axis_w.setSingleStep(0.5)
            spin_axis_w.setValue(self._style.get('axis_line_width', 3))
            spin_axis_w.setToolTip("Grosor de las líneas de los ejes X/Y/Z. Valor típico: 2 a 4. Por defecto: 3.")
            form_ax.addRow("Grosor líneas X/Y/Z:", spin_axis_w)
            fields['grid_color']     = btn_grid
            fields['grid_width']     = spin_grid_w
            fields['axis_label_size'] = spin_label
            fields['axis_line_width'] = spin_axis_w
            outer.addWidget(box_ax)

            box_interp = QGroupBox("Interpolación / suavizado")
            form_interp = QFormLayout(box_interp)
            spin_interp_deg = _NumEdit()
            spin_interp_deg.setRange(0.5, 10.0); spin_interp_deg.setSingleStep(0.5)
            spin_interp_deg.setValue(self._style.get('interp_deg', 2.0))
            spin_interp_deg.setToolTip(
                "Qué tan fina se dibuja la superficie entre los puntos medidos.\n"
                "No cambia los datos, sólo el dibujo.\n"
                "Recomendado: dejar en 2 (por defecto). Bajalo a 1 sólo si vas a\n"
                "exportar una imagen grande y querés más detalle (más lento)."
            )
            form_interp.addRow("Paso de interpolación (°):", spin_interp_deg)
            spin_smoothing = _NumEdit()
            spin_smoothing.setRange(0.0, 500.0); spin_smoothing.setSingleStep(5.0)
            spin_smoothing.setValue(self._style.get('smoothing', 0.0))
            spin_smoothing.setToolTip(
                "0 = la superficie pasa exacto por los datos medidos (recomendado,\n"
                "dejar así salvo que se vea muy ruidosa). Si necesitás suavizar,\n"
                "empezá con 20-50 y andá subiendo de a poco mirando el resultado.\n"
                "Ojo: valores muy altos (200+) empiezan a deformar la forma real."
            )
            form_interp.addRow("Suavizado (factor spline):", spin_smoothing)
            combo_smooth_method_3d = QComboBox()
            combo_smooth_method_3d.setMaximumWidth(120)
            combo_smooth_method_3d.addItems(['gaussian', 'savgol', 'moving_average', 'none'])
            combo_smooth_method_3d.setCurrentText(self._style.get('smoothing_method', 'gaussian'))
            combo_smooth_method_3d.setToolTip(
                "Mismo suavizado circular que el Polar 2D, aplicado en la\n"
                "dirección de azimuth (cada anillo horizontal de la esfera),\n"
                "ANTES de ajustar la superficie. Sólo importa si la ventana de\n"
                "abajo es mayor a 0.\n"
                "gaussian: recomendado para empezar, no genera ondulaciones falsas.\n"
                "savgol: preserva mejor lóbulos/nulos angostos.\n"
                "moving_average: el más simple, puede generar ondulaciones falsas.\n"
                "none: sin efecto, ignora la ventana."
            )
            form_interp.addRow("Tipo de suavizado (azimuth):", combo_smooth_method_3d)
            spin_smooth_win_3d = _NumEdit()
            spin_smooth_win_3d.setDecimals(0)
            spin_smooth_win_3d.setRange(0, 15); spin_smooth_win_3d.setSingleStep(1)
            spin_smooth_win_3d.setValue(self._style.get('smoothing_window', 0))
            spin_smooth_win_3d.setToolTip(
                "Cantidad de puntos vecinos que se promedian entre sí, sobre cada\n"
                "anillo de azimuth. 0 = SIN SUAVIZAR (recomendado para empezar).\n"
                "3 a 5 = suavizado leve. 7 a 9 = fuerte (cuidado, puede borrar\n"
                "lóbulos/nulos reales). No recomendado pasar de 10."
            )
            form_interp.addRow("Intensidad (0 = sin suavizar):", spin_smooth_win_3d)
            fields['interp_deg'] = spin_interp_deg
            fields['smoothing']  = spin_smoothing
            fields['smoothing_method'] = combo_smooth_method_3d
            fields['smoothing_window'] = spin_smooth_win_3d
            outer.addWidget(box_interp)

        elif self._mode == "polar2d":
            box_ax = QGroupBox("Ejes / traza")
            form_ax = QFormLayout(box_ax)
            spin_tick = _NumEdit()
            spin_tick.setRange(6, 30); spin_tick.setSingleStep(1)
            spin_tick.setValue(self._tick_font_size)
            spin_tick.setToolTip("Tamaño de los números de ángulo (0°, 45°, 90°...). Valor típico: 10 a 14. Por defecto: 11.")
            form_ax.addRow("Tamaño de números (grados):", spin_tick)
            spin_ring_font = _NumEdit()
            spin_ring_font.setRange(6, 30); spin_ring_font.setSingleStep(1)
            spin_ring_font.setValue(self._style.get('ring_font_size', 9))
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
            btn_ring = self._make_color_button(dlg, self._style.get('ring_color') or _balloon_mod._RING_LINE)
            btn_ring.setToolTip("Color de los anillos punteados y del eje angular. Click para elegir.")
            form_ax.addRow("Color de anillos/eje:", btn_ring)
            chk_grid = QCheckBox("Mostrar grilla radial")
            chk_grid.setChecked(self._style.get('show_radial_grid', False))
            chk_grid.setToolTip("Grilla radial extra de Plotly, además de los anillos de dB. Normalmente no hace falta, dejar destildado.")
            form_ax.addRow(chk_grid)
            spin_line_w = _NumEdit()
            spin_line_w.setRange(0.5, 8.0); spin_line_w.setSingleStep(0.5)
            spin_line_w.setValue(self._style.get('line_width', 2.5))
            spin_line_w.setToolTip("Grosor de la curva del patrón (sólo aplica con una banda a la vez). Valor típico: 2 a 3. Por defecto: 2.5.")
            form_ax.addRow("Grosor de traza (banda única):", spin_line_w)
            spin_legend = _NumEdit()
            spin_legend.setRange(6, 30); spin_legend.setSingleStep(1)
            spin_legend.setValue(self._style.get('legend_font_size', 12))
            spin_legend.setToolTip("Tamaño de la leyenda cuando comparás varias bandas superpuestas. Valor típico: 11 a 14. Por defecto: 12.")
            form_ax.addRow("Tamaño de leyenda (multibanda):", spin_legend)
            fields['tick_font_size']    = spin_tick
            fields['ring_font_size']    = spin_ring_font
            fields['ring_step']         = spin_ring_step
            fields['ring_label_angle']  = spin_ring_angle
            fields['ring_label_pos']    = combo_ring_pos
            fields['ring_color']        = btn_ring
            fields['show_radial_grid']  = chk_grid
            fields['line_width']        = spin_line_w
            fields['legend_font_size']  = spin_legend
            outer.addWidget(box_ax)

            box_interp = QGroupBox("Interpolación / suavizado")
            form_interp = QFormLayout(box_interp)
            combo_smooth_method = QComboBox()
            combo_smooth_method.setMaximumWidth(120)
            combo_smooth_method.addItems(['gaussian', 'savgol', 'moving_average', 'none'])
            combo_smooth_method.setCurrentText(self._style.get('smoothing_method', 'gaussian'))
            combo_smooth_method.setToolTip(
                "Sólo importa si la 'Intensidad' de abajo es mayor a 0.\n"
                "gaussian: recomendado para empezar, no genera ondulaciones falsas.\n"
                "savgol (Savitzky-Golay): usalo si el gaussiano te 'redondea'\n"
                "  demasiado un lóbulo o nulo que sabés que es real.\n"
                "moving_average: el más simple, pero puede generar\n"
                "  ondulaciones que no existen en la medición real.\n"
                "none: sin suavizar, ignora la intensidad."
            )
            form_interp.addRow("Tipo de suavizado:", combo_smooth_method)
            spin_smooth_win = _NumEdit()
            spin_smooth_win.setDecimals(0)
            spin_smooth_win.setRange(0, 15); spin_smooth_win.setSingleStep(1)
            spin_smooth_win.setValue(self._style.get('smoothing_window', 0))
            spin_smooth_win.setToolTip(
                "Cantidad de puntos vecinos que se promedian entre sí.\n"
                "0 = SIN SUAVIZAR (recomendado para empezar — dejalo así\n"
                "  salvo que el patrón se vea con ruido/dientes de sierra raros).\n"
                "3 a 5 = suavizado leve, buen punto de partida si hace falta.\n"
                "7 a 9 = suavizado fuerte — cuidado, puede borrar lóbulos/nulos reales.\n"
                "No recomendado pasar de 10: empieza a distorsionar la forma real."
            )
            form_interp.addRow("Intensidad (0 = sin suavizar):", spin_smooth_win)
            combo_interp = QComboBox()
            combo_interp.setMaximumWidth(120)
            combo_interp.addItems(['cubic', 'quadratic', 'linear', 'none'])
            combo_interp.setCurrentText(self._style.get('interp_kind', 'cubic'))
            combo_interp.setToolTip(
                "No cambia los datos medidos, sólo cómo se dibuja la curva entre puntos.\n"
                "cubic: recomendado, curva natural (por defecto).\n"
                "quadratic: intermedio.\n"
                "linear: conecta los puntos con rectas (se ve 'picudo', como un diamante).\n"
                "none: sólo los puntos medidos, sin curva — útil para comparar\n"
                "  contra el dato crudo y ver si el suavizado está bien."
            )
            form_interp.addRow("Tipo de interpolación:", combo_interp)
            spin_interp_deg = _NumEdit()
            spin_interp_deg.setRange(0.1, 10.0); spin_interp_deg.setSingleStep(0.5)
            spin_interp_deg.setValue(self._style.get('interp_deg', 1.0))
            spin_interp_deg.setToolTip(
                "Qué tan fina se dibuja la curva. No cambia los datos.\n"
                "Recomendado: dejar en 1 (por defecto).\n"
                "Bajalo a 0.5 sólo si vas a exportar una imagen grande y querés\n"
                "más nitidez. Subilo a 2-5 si sentís que el gráfico va lento."
            )
            form_interp.addRow("Paso de interpolación (°):", spin_interp_deg)
            fields['smoothing_method'] = combo_smooth_method
            fields['smoothing_window'] = spin_smooth_win
            fields['interp_kind']      = combo_interp
            fields['interp_deg']       = spin_interp_deg
            outer.addWidget(box_interp)

        elif self._mode == "spectrum":
            box_sp = QGroupBox("Barras / grilla")
            form_sp = QFormLayout(box_sp)
            btn_bar = self._make_color_button(dlg, self._style.get('bar_color') or "#5865f2")
            btn_bar.setToolTip("Color de las barras cuando el modo de vista está en 'Global'. No aplica al modo 'Por toma' (usa un color distinto por azimuth).")
            form_sp.addRow("Color de barras (modo Global):", btn_bar)
            btn_grid_sp = self._make_color_button(dlg, self._style.get('grid_color') or _balloon_mod._GRID_COL)
            btn_grid_sp.setToolTip("Color de la grilla de los ejes.")
            form_sp.addRow("Color de grilla:", btn_grid_sp)
            fields['bar_color']   = btn_bar
            fields['grid_color2'] = btn_grid_sp
            outer.addWidget(box_sp)

        def _apply():
            self._push_undo_snapshot()

            if self._mode != "spectrum":
                try:
                    self._min_db = float(fields['min_db'].text()) if fields['min_db'].text().strip() else None
                    self._max_db = float(fields['max_db'].text()) if fields['max_db'].text().strip() else None
                except ValueError:
                    pass

            new_style = dict(self._style)
            new_style['bg_color'] = fields['bg_color'].color_hex

            if self._mode in ("3d", "sphere"):
                self._axis_color = fields['grid_color'].color_hex
                self._axis_width = fields['grid_width'].value()
                new_style['axis_label_size'] = fields['axis_label_size'].value()
                new_style['axis_line_width'] = fields['axis_line_width'].value()
                new_style['interp_deg']      = fields['interp_deg'].value()
                new_style['smoothing']       = fields['smoothing'].value()
                new_style['smoothing_method'] = fields['smoothing_method'].currentText()
                new_style['smoothing_window'] = fields['smoothing_window'].value()
            elif self._mode == "polar2d":
                self._tick_font_size = fields['tick_font_size'].value()
                new_style['ring_font_size']    = fields['ring_font_size'].value()
                new_style['ring_step']         = fields['ring_step'].value()
                new_style['ring_label_angle']  = fields['ring_label_angle'].value()
                new_style['ring_label_pos']    = fields['ring_label_pos'].currentText()
                new_style['ring_color']        = fields['ring_color'].color_hex
                new_style['show_radial_grid']  = fields['show_radial_grid'].isChecked()
                new_style['line_width']        = fields['line_width'].value()
                new_style['legend_font_size']  = fields['legend_font_size'].value()
                new_style['smoothing_method']  = fields['smoothing_method'].currentText()
                new_style['smoothing_window']  = fields['smoothing_window'].value()
                new_style['interp_kind']       = fields['interp_kind'].currentText()
                new_style['interp_deg']        = fields['interp_deg'].value()
            elif self._mode == "spectrum":
                new_style['bar_color']  = fields['bar_color'].color_hex
                new_style['grid_color'] = fields['grid_color2'].color_hex

            self._style = new_style
            self.view.set_db_range(self._min_db, self._max_db)
            if self._mode in ("3d", "sphere"):
                self.view.set_axis_style(self._axis_color, self._axis_width)
            elif self._mode == "polar2d":
                self.view.set_tick_font_size(self._tick_font_size)
            self.view.set_style(self._style)
            self.properties_applied.emit()

        btn_row   = QHBoxLayout()
        btn_apply = QPushButton("Aplicar")
        btn_close = QPushButton("Cerrar")
        btn_apply.clicked.connect(_apply)
        btn_close.clicked.connect(close_cb)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(dlg)
        return scroll

    def _prompt_compare_bands(self):
        bands = self.view._bands
        if bands is None or len(bands) == 0:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Comparar bandas — Polar 2D")
        dlg.resize(240, 400)
        outer = QVBoxLayout(dlg)
        outer.addWidget(QLabel("Seleccioná dos o más bandas para superponer:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        inner  = QVBoxLayout(holder)
        checks = []
        selected_now = set(self._compare_indices or [])
        for i, hz in enumerate(bands):
            cb = QCheckBox(f"{float(hz):.0f} Hz")
            cb.setChecked(i in selected_now)
            checks.append(cb)
            inner.addWidget(cb)
        inner.addStretch()
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        outer.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = [i for i, cb in enumerate(checks) if cb.isChecked()]
        self._compare_indices = selected if len(selected) > 1 else None
        self.view.set_compare_bands(self._compare_indices)

    def _prompt_band_properties(self):
        if not self._compare_indices:
            return
        bands = self.view._bands

        dlg = QDialog(self)
        dlg.setWindowTitle("Propiedades de bandas")
        form = QFormLayout(dlg)

        rows = {}   # band_index -> (btn_color, spin_width, combo_dash)
        for pos, i in enumerate(self._compare_indices):
            style   = self._compare_styles.get(i, {})
            default_color = _COMPARE_COLORS[pos % len(_COMPARE_COLORS)]

            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)

            btn_color = QPushButton()
            btn_color.setFixedSize(28, 20)
            btn_color.color_hex = style.get('color', default_color)
            btn_color.setStyleSheet(f"background:{btn_color.color_hex};border:1px solid #555;")

            def _pick(checked=False, _btn=btn_color):
                c = QColorDialog.getColor(self._to_qcolor(_btn.color_hex), dlg)
                if c.isValid():
                    _btn.color_hex = c.name()
                    _btn.setStyleSheet(f"background:{_btn.color_hex};border:1px solid #555;")
            btn_color.clicked.connect(_pick)
            row.addWidget(btn_color)

            spin_width = _NumEdit()
            spin_width.setRange(0.5, 10.0)
            spin_width.setSingleStep(0.5)
            spin_width.setValue(style.get('width', 2.5))
            row.addWidget(spin_width)

            combo_dash = QComboBox()
            combo_dash.addItems(_DASH_STYLES)
            combo_dash.setCurrentText(style.get('dash', 'solid'))
            row.addWidget(combo_dash)

            rows[i] = (btn_color, spin_width, combo_dash)
            form.addRow(f"{float(bands[i]):.0f} Hz:", row_widget)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        for i, (btn_color, spin_width, combo_dash) in rows.items():
            self._compare_styles[i] = {
                'color': btn_color.color_hex,
                'width': spin_width.value(),
                'dash':  combo_dash.currentText(),
            }
        self.view.set_compare_styles(self._compare_styles)

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
        snap = self._props_undo_stack.pop()
        self._style          = snap['style']
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
        return True

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
        self.view.export_image(path, dpi=dpi, fmt=fmt, on_done=on_done)


# ─────────────────────────────────────────────────────────────────────────────

class TabDirectividad(QWidget):
    log      = pyqtSignal(str)
    computed = pyqtSignal(object, str)  # (thetas_np, status_text)

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
        self._show_info        = True
        self._current_band_idx = 0

        # Estado de controles del ribbon — actualizados por apply_display_params()
        self._hz_min      = 200.0
        self._hz_max      = 8000.0
        self._sym         = "none"
        self._nota        = "Todo el audio"
        self._spec_data   = 0       # 0=raw, 1=eq
        self._spec_global = True
        self._view_checks = {
            "3d": False, "sphere": True, "polar2d": True, "spectrum": False
        }

        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_right_panel(), 1)

    def _make_right_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

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
            sec.properties_requested.connect(
                lambda m=mode: self._show_properties_panel(m))
            sec.properties_applied.connect(
                lambda m=mode: setattr(self, '_last_props_mode', m))

        # Ctrl+Z deshace el último "Aplicar" de Propiedades (cualquier gráfico).
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo_properties)

        # Grilla 2×2 de paneles arrastrables — QMainWindow anidado con
        # QDockWidgets, igual mecanismo que usa el dock del Log: se pueden
        # mover, reacomodar o flotar arrastrándolos con el mouse.
        self._dock_host = QMainWindow()
        self._dock_host.setWindowFlags(Qt.WindowType.Widget)
        # Por default Qt no permite anidar/reacomodar libremente los docks al
        # arrastrar (dockNestingEnabled=False) — eso es lo que hacía fallar
        # el "ponelo al costado / arriba" a veces. Con esto habilitado, el
        # área de destino se puede volver a partir en cualquier dirección.
        self._dock_host.setDockNestingEnabled(True)
        self._dock_host.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks |
            QMainWindow.DockOption.AllowNestedDocks |
            QMainWindow.DockOption.AllowTabbedDocks
        )

        self._docks: dict[str, QDockWidget] = {}
        for mode, sec in self._sections.items():
            dock = QDockWidget(self._section_titles[mode], self._dock_host)
            dock.setWidget(sec)
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetMovable |
                QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
            dock.setVisible(self._view_checks.get(mode, True))
            self._docks[mode] = dock

        dock_host_area = Qt.DockWidgetArea.TopDockWidgetArea
        self._dock_host.addDockWidget(dock_host_area, self._docks["3d"])
        self._dock_host.splitDockWidget(
            self._docks["3d"], self._docks["sphere"], Qt.Orientation.Horizontal)
        self._dock_host.splitDockWidget(
            self._docks["3d"], self._docks["polar2d"], Qt.Orientation.Vertical)
        self._dock_host.splitDockWidget(
            self._docks["sphere"], self._docks["spectrum"], Qt.Orientation.Vertical)

        # Panel de Propiedades compartido — no modal, siempre al costado
        # derecho de la grilla 2×2 (en vez de un diálogo bloqueante),
        # reutilizado y repoblado según cuál gráfico lo pidió (ver
        # _show_properties_panel). Se usa un QSplitter en vez de acoplarlo
        # como un QDockWidget más dentro de _dock_host porque los 4 gráficos
        # ya ocupan las 4 "esquinas" de ese QMainWindow anidado (todos bajo
        # TopDockWidgetArea) — agregar un dock ahí con RightDockWidgetArea
        # termina cayendo debajo de la grilla en vez de al costado, ya que
        # Top/Bottom tienen prioridad sobre las esquinas por default en Qt.
        self._props_panel = QWidget()
        self._props_panel.setMinimumWidth(260)
        self._props_panel.setMaximumWidth(340)
        props_lay = QVBoxLayout(self._props_panel)
        props_lay.setContentsMargins(4, 4, 4, 4)

        title_row = QHBoxLayout()
        self._props_title = QLabel("Propiedades")
        self._props_title.setStyleSheet("font-weight:600;")
        btn_props_close = QPushButton("✕")
        btn_props_close.setFixedSize(22, 22)
        btn_props_close.setToolTip("Cerrar panel de Propiedades")
        btn_props_close.clicked.connect(lambda: self._props_panel.hide())
        title_row.addWidget(self._props_title, 1)
        title_row.addWidget(btn_props_close)
        props_lay.addLayout(title_row)

        self._props_content_holder = QVBoxLayout()
        props_lay.addLayout(self._props_content_holder, 1)
        self._props_panel.hide()

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self._dock_host)
        self._main_splitter.addWidget(self._props_panel)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)

        lay.addWidget(self._main_splitter, 1)

        self.band_selector = BandSelectorWidget()
        self.band_selector.band_changed.connect(self._on_band_changed)
        lay.addWidget(self.band_selector)

        return w

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
            if self._props_panel.isVisible():
                self._show_properties_panel(mode)

    def _show_properties_panel(self, mode: str):
        """Repuebla el panel de Propiedades compartido con los campos del
        gráfico indicado y lo muestra (no modal, siempre al costado
        derecho de la grilla de gráficos, ver QSplitter en _make_right_panel)."""
        sec = self._sections[mode]

        while self._props_content_holder.count():
            item = self._props_content_holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        widget = sec.build_properties_widget(self._props_panel.hide)
        self._props_content_holder.addWidget(widget)
        self._props_title.setText(f"Propiedades — {self._section_titles[mode]}")
        self._props_panel.show()
        if self._main_splitter.sizes()[1] < 10:
            total = sum(self._main_splitter.sizes()) or self.width() or 1000
            props_w = max(260, min(340, int(total * 0.18)))
            self._main_splitter.setSizes([max(total - props_w, 100), props_w])

    def _apply_view_checks(self, view_checks: dict):
        for mode, checked in view_checks.items():
            if mode in self._docks:
                self._docks[mode].setVisible(checked)
                self._view_checks[mode] = checked
        self._update_band_selector_visibility()

    def _update_band_selector_visibility(self):
        any_non_spectrum = any(
            self._view_checks[mode]
            for mode in ("3d", "sphere", "polar2d")
        )
        self.band_selector.setVisible(any_non_spectrum)

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

        # Escala fina (0–1000) para que la barra avance de forma suave dentro
        # de cada ítem, en base al progreso por posición que ya reporta
        # compute_directivity(), en vez de saltar sólo entre ítems completos.
        _PROGRESS_SCALE = 1000
        dlg = QProgressDialog("Iniciando…", None, 0, _PROGRESS_SCALE, self.window())
        dlg.setWindowTitle("Calculando directividad")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)

        self._worker = _ComputeAllWorker(self._ma, bands, ref_az, ref_th)
        self._worker.log.connect(self.log)
        self._worker.progress.connect(
            lambda cur, tot, lbl, _d=dlg: (
                _d.setLabelText(f"Calculando: {lbl}" if lbl else "Finalizando…"),
            )
        )
        self._worker.overall_progress.connect(
            lambda frac, _d=dlg: _d.setValue(int(frac * _PROGRESS_SCALE))
        )
        self._worker.all_done.connect(lambda _d=dlg: self._on_all_done(_d))
        self._worker.error.connect(lambda msg, _d=dlg: (
            _d.close(), self._on_error(msg)
        ))

        self.log.emit(
            f"[Directividad] Iniciando cómputo — "
            f"1 audio completo + {n_notes} nota(s)…"
        )
        self._worker.start()

    def _on_all_done(self, dlg: QProgressDialog):
        dlg.setValue(dlg.maximum())
        dlg.close()
        # Mostrar resultados del audio completo por defecto
        self._nota = "Todo el audio"
        self._show_results(self._ma)
        if self._ma.dir_levels is not None:
            status = (
                f"Dir. calculada — {self._ma.dir_levels.shape}  |  "
                f"{self._ma.dir_freqs[0]:.0f}–{self._ma.dir_freqs[-1]:.0f} Hz"
            )
            self.computed.emit(
                np.array([t for t in self._ma.thetas if t != 'ref'],
                         dtype=np.float32),
                status,
            )
        self.log.emit("[Directividad] Todas las configuraciones calculadas.")

    def load_from_npz(self, data: dict):
        """Carga resultados desde el dict devuelto por data_store.load_results()."""
        self._full_levels   = data['dir_levels'].astype(np.float32)
        self._full_azimuths = data['azimuths'].astype(np.float32)
        self._full_thetas   = data['thetas'].astype(np.float32)
        self._full_bands    = data['dir_freqs'].astype(np.float32)

        self._eq_ref_spl = data['spl_ref'].astype(np.float32)
        if 'spl_ref_per_az' in data:
            self._raw_ref_spl = data['spl_ref_per_az'].astype(np.float32)
        else:
            self._raw_ref_spl = None   # NPZ antiguo, guardado sin el espectro por toma

        self._refresh_display()

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

        self._show_info = params.get('show_info', True)
        for sec in self._sections.values():
            sec.set_show_info(self._show_info)

        view_checks = params.get('view_checks', {})
        if view_checks:
            self._apply_view_checks(view_checks)

        # Si cambió la nota, recargar datos desde el MA correspondiente
        if self._nota != old_nota:
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

        mode_label = _MODE_LABELS.get(mode, mode)
        nota = (self._nota
                .replace("Todo el audio", "todo")
                .replace(" ", "_"))

        if mode != "spectrum":
            bi   = min(self._current_band_idx, len(self._full_bands) - 1)
            freq = int(round(float(self._full_bands[bi])))
            suggested = f"dir_{mode_label}_{freq}Hz_{nota}.png"
        else:
            suggested = f"dir_{mode_label}_{nota}.png"

        filters = "PNG (*.png);;SVG vectorial (*.svg);;JPEG (*.jpg);;WEBP (*.webp)"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Guardar imagen", suggested, filters
        )
        if not path:
            return

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
        else:
            dpi, ok = QInputDialog.getInt(
                self, "Resolución de exportación", "DPI:", 300, 72, 1200, 1
            )
            if not ok:
                return

        self._sections[mode].export_image(path, dpi=dpi, fmt=fmt)

    def export_all_images(self, folder: str, prefix: str, dpi: int = 300):
        """
        Exporta de una sola vez las imágenes de todas las vistas habilitadas
        (pills del ribbon), para todas las bandas del rango actualmente
        analizado (hz_min/hz_max). El espectro no depende de la banda, así
        que se exporta una única vez.

        Nombres: {prefix}_{freq}Hz_{vista}.png  (3D/Esfera/Polar2D)
                 {prefix}_{vista}.png            (Espectro)
        """
        if self._full_bands is None:
            self.log.emit("[Dir] Sin datos para exportar.")
            return

        mask = (self._full_bands >= self._hz_min) & (self._full_bands <= self._hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)
        band_indices = np.nonzero(mask)[0].tolist()

        tasks: list[tuple[str, int | None, str]] = []
        for mode in ("3d", "sphere", "polar2d"):
            if not self._view_checks.get(mode, False):
                continue
            for bi in band_indices:
                freq = int(round(float(self._full_bands[bi])))
                tasks.append((mode, bi, f"{prefix}_{freq}Hz_{_MODE_LABELS[mode]}.png"))
        if self._view_checks.get("spectrum", False):
            tasks.append(("spectrum", None, f"{prefix}_{_MODE_LABELS['spectrum']}.png"))

        if not tasks:
            self.log.emit("[Dir] No hay vistas habilitadas para exportar.")
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
                path, dpi=self._export_dpi, on_done=_after_export))
        else:
            sec.export_image(path, dpi=self._export_dpi, on_done=_after_export)

    def apply_theme(self, palette: dict):
        """Propaga el cambio de tema a todas las secciones de visualización."""
        for sec in self._sections.values():
            sec.view.apply_theme(palette)
