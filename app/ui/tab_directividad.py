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
    QMainWindow, QDockWidget, QProgressDialog, QFileDialog, QPushButton,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QDoubleSpinBox, QComboBox,
    QColorDialog, QInputDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QPoint
from PyQt6.QtGui import QColor

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
    log            = pyqtSignal(str)
    save_requested = pyqtSignal(str)   # emite el modo ("3d", "sphere", etc.)

    def __init__(self, title: str, mode: str, parent=None):
        super().__init__(parent)
        self._mode   = mode
        self._min_db: float | None = None
        self._max_db: float | None = None
        self._compare_indices: list | None = None   # sólo relevante para polar2d
        self._compare_styles: dict = {}             # {band_index: {'color','width','dash'}}
        self._tick_font_size: float = 11            # tamaño números ejes (polar2d)
        self._axis_color: str | None = None         # color de grilla 3D (3d/sphere), None = tema
        self._axis_width: float = 1                 # grosor de grilla 3D

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.view = BalloonView()
        self.view.set_view_mode(mode)
        self.view.log.connect(self.log)
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

        act_top = act_bottom = act_front = act_back = act_axis_props = None
        if self._mode in ("3d", "sphere"):
            view_menu  = menu.addMenu("Vista")
            act_top    = view_menu.addAction("Arriba")
            act_bottom = view_menu.addAction("Abajo")
            act_front  = view_menu.addAction("Frente")
            act_back   = view_menu.addAction("Atrás")
            act_axis_props = menu.addAction("Propiedades de ejes…")
            menu.addSeparator()

        act_compare = act_properties = act_tick_size = None
        if self._mode == "polar2d":
            act_compare = menu.addAction("Comparar bandas…")
            if self._compare_indices:
                act_properties = menu.addAction("Propiedades de bandas…")
            act_tick_size = menu.addAction("Tamaño de números de ejes…")
            menu.addSeparator()

        act_scale = menu.addAction("Definir escala…")
        act_auto  = menu.addAction("Autoescala")
        act_auto.setEnabled(self._min_db is not None or self._max_db is not None)
        menu.addSeparator()
        act_save = menu.addAction("Guardar imagen…")

        action = menu.exec(self.view._web.mapToGlobal(pos))
        if action == act_scale:
            self._prompt_scale()
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
        elif action == act_properties:
            self._prompt_band_properties()
        elif action == act_tick_size:
            self._prompt_tick_font_size()
        elif action == act_axis_props:
            self._prompt_axis_style()

    def _prompt_tick_font_size(self):
        size, ok = QInputDialog.getDouble(
            self, "Tamaño de números de ejes",
            "Tamaño de fuente (pt):",
            self._tick_font_size, 6.0, 30.0, 1,
        )
        if ok:
            self._tick_font_size = size
            self.view.set_tick_font_size(size)

    def _prompt_axis_style(self):
        from plot import balloon as _balloon_mod

        dlg = QDialog(self)
        dlg.setWindowTitle("Propiedades de ejes")
        form = QFormLayout(dlg)

        current_color = self._axis_color or _balloon_mod._GRID_COL
        btn_color = QPushButton()
        btn_color.setFixedSize(28, 20)
        btn_color.color_hex = current_color
        btn_color.setStyleSheet(f"background:{current_color};border:1px solid #555;")

        def _pick(_btn=btn_color):
            c = QColorDialog.getColor(QColor(_btn.color_hex), dlg)
            if c.isValid():
                _btn.color_hex = c.name()
                _btn.setStyleSheet(f"background:{_btn.color_hex};border:1px solid #555;")
        btn_color.clicked.connect(_pick)
        form.addRow("Color:", btn_color)

        spin_width = QDoubleSpinBox()
        spin_width.setRange(0.5, 8.0)
        spin_width.setSingleStep(0.5)
        spin_width.setValue(self._axis_width)
        form.addRow("Grosor:", spin_width)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._axis_color = btn_color.color_hex
        self._axis_width = spin_width.value()
        self.view.set_axis_style(self._axis_color, self._axis_width)

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

            def _pick(_btn=btn_color):
                c = QColorDialog.getColor(QColor(_btn.color_hex), dlg)
                if c.isValid():
                    _btn.color_hex = c.name()
                    _btn.setStyleSheet(f"background:{_btn.color_hex};border:1px solid #555;")
            btn_color.clicked.connect(_pick)
            row.addWidget(btn_color)

            spin_width = QDoubleSpinBox()
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

    def _prompt_scale(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Definir escala")
        form = QFormLayout(dlg)

        le_min = QLineEdit("" if self._min_db is None else str(self._min_db))
        le_min.setPlaceholderText("auto")
        le_max = QLineEdit("" if self._max_db is None else str(self._max_db))
        le_max.setPlaceholderText("auto")
        form.addRow("Min (dB):", le_min)
        form.addRow("Max (dB):", le_max)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._min_db = float(le_min.text()) if le_min.text().strip() else None
            self._max_db = float(le_max.text()) if le_max.text().strip() else None
        except ValueError:
            return
        self.view.set_db_range(self._min_db, self._max_db)

    def _reset_scale(self):
        self._min_db = None
        self._max_db = None
        self.view.set_db_range(None, None)

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

    def export_image(self, path: str, on_done=None):
        self.view.export_image(path, on_done=on_done)


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
            "3d": True, "sphere": True, "polar2d": True, "spectrum": True
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
        for mode, sec in self._sections.items():
            sec.log.connect(self.log)
            sec.save_requested.connect(self._save_section)

        # Grilla 2×2 de paneles arrastrables — QMainWindow anidado con
        # QDockWidgets, igual mecanismo que usa el dock del Log: se pueden
        # mover, reacomodar o flotar arrastrándolos con el mouse.
        self._dock_host = QMainWindow()
        self._dock_host.setWindowFlags(Qt.WindowType.Widget)

        _titles = {
            "3d": "Superficie 3D", "sphere": "Esfera",
            "polar2d": "Polar 2D", "spectrum": "Espectro",
        }
        self._docks: dict[str, QDockWidget] = {}
        for mode, sec in self._sections.items():
            dock = QDockWidget(_titles[mode], self._dock_host)
            dock.setWidget(sec)
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetMovable |
                QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
            self._docks[mode] = dock

        dock_host_area = Qt.DockWidgetArea.TopDockWidgetArea
        self._dock_host.addDockWidget(dock_host_area, self._docks["3d"])
        self._dock_host.splitDockWidget(
            self._docks["3d"], self._docks["sphere"], Qt.Orientation.Horizontal)
        self._dock_host.splitDockWidget(
            self._docks["3d"], self._docks["polar2d"], Qt.Orientation.Vertical)
        self._dock_host.splitDockWidget(
            self._docks["sphere"], self._docks["spectrum"], Qt.Orientation.Vertical)

        lay.addWidget(self._dock_host, 1)

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

        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar imagen", suggested, "PNG (*.png)"
        )
        if not path:
            return

        self._sections[mode].export_image(path)

    def export_all_images(self, folder: str, prefix: str):
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
            QTimer.singleShot(250, lambda: sec.export_image(path, on_done=_after_export))
        else:
            sec.export_image(path, on_done=_after_export)

    def apply_theme(self, palette: dict):
        """Propaga el cambio de tema a todas las secciones de visualización."""
        for sec in self._sections.values():
            sec.view.apply_theme(palette)
