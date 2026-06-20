"""
ui/tab_directividad.py — Directividad: cómputo y visualización multi-panel.
Los controles están en el ribbon global (ui/ribbon.py).
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.worker import Worker
from ui.balloon_view import BalloonView
from ui.band_selector import BandSelectorWidget
from plot.balloon import COLORSCALES


def _le(default="", width=75, placeholder="") -> QLineEdit:
    w = QLineEdit(str(default))
    w.setPlaceholderText(placeholder)
    w.setFixedWidth(width)
    w.wheelEvent = lambda e: e.ignore()
    return w


class _ViewSection(QWidget):
    """
    Panel para un único modo de visualización.
    Incluye barra de escala independiente (min/max dB) con modo auto por defecto.
    """
    log = pyqtSignal(str)

    def __init__(self, title: str, mode: str, parent=None):
        super().__init__(parent)
        self._mode = mode

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Cabecera ──────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(30)
        hdr.setStyleSheet(
            "QWidget{background:#0f1119;border-bottom:1px solid #252840;}"
        )
        h = QHBoxLayout(hdr)
        h.setContentsMargins(8, 2, 8, 2)
        h.setSpacing(6)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            "color:#c8d4f0;font-size:9pt;font-weight:600;background:transparent;"
        )
        h.addWidget(lbl)
        h.addStretch()

        lbl_scale = QLabel("Escala  Min:")
        lbl_scale.setStyleSheet("color:#8a96be;font-size:9pt;background:transparent;")
        h.addWidget(lbl_scale)

        self.le_min = _le("", 52, "auto")
        self.le_min.setStyleSheet("font-size:8pt;padding:1px 4px;")
        self.le_min.editingFinished.connect(self._apply_scale)
        h.addWidget(self.le_min)

        lbl_max = QLabel("Max:")
        lbl_max.setStyleSheet("color:#8a96be;font-size:9pt;background:transparent;")
        h.addWidget(lbl_max)

        self.le_max = _le("", 52, "auto")
        self.le_max.setStyleSheet("font-size:8pt;padding:1px 4px;")
        self.le_max.editingFinished.connect(self._apply_scale)
        h.addWidget(self.le_max)

        btn_rst = QPushButton("↺")
        btn_rst.setToolTip("Volver a escala automática")
        btn_rst.setFixedSize(22, 22)
        btn_rst.setStyleSheet(
            "QPushButton{background:#1e2238;border:1px solid #3a3f60;"
            "border-radius:3px;color:#9aa6cc;font-size:10pt;padding:0;}"
            "QPushButton:hover{background:#2a2d45;}"
        )
        btn_rst.clicked.connect(self._reset_scale)
        h.addWidget(btn_rst)

        lay.addWidget(hdr)

        # ── BalloonView ────────────────────────────────────────────────────
        self.view = BalloonView()
        self.view.set_view_mode(mode)
        self.view.log.connect(self.log)
        lay.addWidget(self.view, 1)

        self.setMinimumHeight(80)

    def _apply_scale(self):
        try:
            mn = float(self.le_min.text()) if self.le_min.text().strip() else None
            mx = float(self.le_max.text()) if self.le_max.text().strip() else None
        except ValueError:
            return
        self.view.set_db_range(mn, mx)

    def _reset_scale(self):
        self.le_min.clear()
        self.le_max.clear()
        self.view.set_db_range(None, None)

    def set_data(self, **kwargs):
        self.view.set_data(**kwargs)

    def set_band(self, index: int):
        self.view.set_band(index)

    def set_colorscale(self, name: str):
        self.view.set_colorscale(name)

    def set_el_index(self, idx):
        self.view.set_el_index(idx)


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
        for sec in self._sections.values():
            sec.log.connect(self.log)

        # Grilla 2×2 con splitters anidados
        self._row_top = QSplitter(Qt.Orientation.Horizontal)
        self._row_top.setChildrenCollapsible(True)
        self._row_top.addWidget(self._sections["3d"])
        self._row_top.addWidget(self._sections["sphere"])

        self._row_bot = QSplitter(Qt.Orientation.Horizontal)
        self._row_bot.setChildrenCollapsible(True)
        self._row_bot.addWidget(self._sections["polar2d"])
        self._row_bot.addWidget(self._sections["spectrum"])

        self._views_splitter = QSplitter(Qt.Orientation.Vertical)
        self._views_splitter.setChildrenCollapsible(True)
        self._views_splitter.addWidget(self._row_top)
        self._views_splitter.addWidget(self._row_bot)

        self._views_splitter.setSizes([500, 500])
        self._row_top.setSizes([500, 500])
        self._row_bot.setSizes([500, 500])

        lay.addWidget(self._views_splitter, 1)

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

    def _run_compute(self, bands: str, threshold: float, ref_az: int, ref_th: int):
        ma = self._get_current_ma()
        ma.compute_directivity(
            bands          = bands,
            threshold_spl  = threshold,
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
            if sec.isVisible():
                sec.set_data(**kwargs)
                if self._current_el_idx is not None:
                    sec.set_el_index(self._current_el_idx)

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

    def _apply_view_checks(self, view_checks: dict):
        for mode, checked in view_checks.items():
            if mode in self._sections:
                self._sections[mode].setVisible(checked)
                self._view_checks[mode] = checked
        top_vis = self._view_checks["3d"] or self._view_checks["sphere"]
        bot_vis = self._view_checks["polar2d"] or self._view_checks["spectrum"]
        self._row_top.setVisible(top_vis)
        self._row_bot.setVisible(bot_vis)
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
                vad: float, ref_az: int, ref_th: int):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self._hz_min = hz_min
        self._hz_max = hz_max
        self.log.emit("[Directividad] Calculando…")
        self._worker = Worker(
            lambda: self._run_compute(bands, vad, ref_az, ref_th)
        )
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_compute_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def load_from_npz(self, data: dict):
        """Carga resultados desde el dict devuelto por data_store.load_results()."""
        self._full_levels   = data['dir_levels'].astype(np.float32)
        self._full_azimuths = data['azimuths'].astype(np.float32)
        self._full_thetas   = data['thetas'].astype(np.float32)
        self._full_bands    = data['dir_freqs'].astype(np.float32)

        self._raw_ref_spl = None   # NPZ solo guarda patrón relativo
        self._eq_ref_spl  = data['spl_ref'].astype(np.float32)

        self._refresh_display()

    def apply_display_params(self, params: dict):
        """
        Actualiza todos los parámetros de visualización con los valores
        devueltos por ribbon.get_dir_display_params().
        """
        self._hz_min      = params.get('hz_min', 200.0)
        self._hz_max      = params.get('hz_max', 8000.0)
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

        view_checks = params.get('view_checks', {})
        if view_checks:
            self._apply_view_checks(view_checks)

        self._refresh_display()
