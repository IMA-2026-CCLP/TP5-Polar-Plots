"""
ui/tab_directividad.py — Tab Directividad: cómputo y visualización multi-panel.
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QComboBox, QFileDialog, QFrame,
    QCheckBox, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.worker import Worker
from core.data_store import save_results
from ui.balloon_view import BalloonView
from ui.band_selector import BandSelectorWidget
from plot.balloon import COLORSCALES


def _le(default="", width=75, placeholder="") -> QLineEdit:
    """QLineEdit sin flechas ni rueda del mouse."""
    w = QLineEdit(str(default))
    w.setPlaceholderText(placeholder)
    w.setFixedWidth(width)
    w.wheelEvent = lambda e: e.ignore()
    return w


class _ViewSection(QWidget):
    """
    Panel para un único modo de visualización (3d / sphere / polar2d / spectrum).
    Incluye barra de escala independiente (min/max dB) con modo automático por defecto.
    """
    def __init__(self, title: str, mode: str, parent=None):
        super().__init__(parent)
        self._mode = mode

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Barra de cabecera ──────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(30)
        hdr.setStyleSheet(
            "QWidget{background:#12141e;border-bottom:1px solid #2a2d3e;}"
        )
        h = QHBoxLayout(hdr)
        h.setContentsMargins(8, 2, 8, 2)
        h.setSpacing(6)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            "color:#a0aac0;font-size:9pt;font-weight:600;background:transparent;"
        )
        h.addWidget(lbl)
        h.addStretch()

        lbl_scale = QLabel("Escala  Min:")
        lbl_scale.setStyleSheet("color:#5a6080;font-size:8pt;background:transparent;")
        h.addWidget(lbl_scale)

        self.le_min = _le("", 52, "auto")
        self.le_min.setStyleSheet("font-size:8pt;padding:1px 4px;")
        self.le_min.editingFinished.connect(self._apply_scale)
        h.addWidget(self.le_min)

        lbl_max = QLabel("Max:")
        lbl_max.setStyleSheet("color:#5a6080;font-size:8pt;background:transparent;")
        h.addWidget(lbl_max)

        self.le_max = _le("", 52, "auto")
        self.le_max.setStyleSheet("font-size:8pt;padding:1px 4px;")
        self.le_max.editingFinished.connect(self._apply_scale)
        h.addWidget(self.le_max)

        btn_rst = QPushButton("↺")
        btn_rst.setToolTip("Volver a escala automática")
        btn_rst.setFixedSize(22, 22)
        btn_rst.setStyleSheet(
            "QPushButton{background:#1e2134;border:1px solid #3a3d55;"
            "border-radius:3px;color:#8892b0;font-size:10pt;padding:0;}"
            "QPushButton:hover{background:#2a2d45;}"
        )
        btn_rst.clicked.connect(self._reset_scale)
        h.addWidget(btn_rst)

        lay.addWidget(hdr)

        # ── BalloonView bloqueado al modo ──────────────────────────────────
        self.view = BalloonView()
        self.view.set_view_mode(mode)
        lay.addWidget(self.view, 1)

        self.setMinimumHeight(80)

    # ── Escala ────────────────────────────────────────────────────────────

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

    # ── Delegación ────────────────────────────────────────────────────────

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
    log = pyqtSignal(str)

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
        self._current_el_idx = None   # None = auto
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_ribbon())
        root.addWidget(self._make_right_panel(), 1)

    # ── Ribbon ────────────────────────────────────────────────────────────

    _RIBBON_STYLE = """
        QWidget#dir_ribbon {
            background: #161829;
            border-bottom: 1px solid #2a2d3e;
        }
        QWidget#dir_ribbon QLabel {
            color: #8892b0; font-size: 8pt;
        }
        QWidget#dir_ribbon QPushButton {
            background: #1e2134; border: 1px solid #3a3d55;
            border-radius: 4px; color: #c8d0e8;
            font-size: 8pt; padding: 3px 8px; min-height: 20px;
        }
        QWidget#dir_ribbon QPushButton:hover  { background: #2a2d45; }
        QWidget#dir_ribbon QPushButton#btn_primary {
            background: #3d4f9f; border-color: #5865c0; color: #fff;
        }
        QWidget#dir_ribbon QPushButton#btn_primary:hover { background: #4a5db8; }
        QWidget#dir_ribbon QPushButton:disabled { color: #3a3d55; border-color: #252840; }
        QWidget#dir_ribbon QComboBox {
            background: #1e2134; border: 1px solid #3a3d55;
            border-radius: 3px; color: #c8d0e8;
            font-size: 8pt; padding: 2px 4px; min-height: 18px;
        }
        QWidget#dir_ribbon QComboBox::drop-down { border: none; width: 14px; }
        QWidget#dir_ribbon QLineEdit {
            background: #1e2134; border: 1px solid #3a3d55;
            border-radius: 3px; color: #c8d0e8;
            font-size: 8pt; padding: 2px 4px; min-height: 18px;
        }
        QWidget#dir_ribbon QCheckBox {
            color: #8892b0; font-size: 8pt; spacing: 4px;
        }
    """

    def _make_ribbon(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("dir_ribbon")
        bar.setFixedHeight(110)
        bar.setStyleSheet(self._RIBBON_STYLE)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 2)
        lay.setSpacing(0)

        lay.addWidget(self._rg_compute())
        lay.addWidget(_dir_vsep())
        lay.addWidget(self._rg_nota())
        lay.addWidget(_dir_vsep())
        lay.addWidget(self._rg_display())
        lay.addWidget(_dir_vsep())
        lay.addWidget(self._rg_spectrum())
        lay.addWidget(_dir_vsep())
        lay.addWidget(self._rg_export())
        lay.addStretch()

        return bar

    def _rg_compute(self) -> QWidget:
        w, body = _dir_group("CÓMPUTO")

        r1 = QHBoxLayout(); r1.setSpacing(5)
        r1.addWidget(QLabel("Bandas:"))
        self.combo_bands = QComboBox(); self.combo_bands.setFixedWidth(60)
        self.combo_bands.addItems(["1/3", "octave"])
        r1.addWidget(self.combo_bands)
        r1.addSpacing(6)
        r1.addWidget(QLabel("Hz:"))
        self.le_hz_min = _le(200, 56); self.le_hz_min.setPlaceholderText("mín")
        self.le_hz_min.editingFinished.connect(self._on_hz_range_changed)
        r1.addWidget(self.le_hz_min)
        r1.addWidget(QLabel("–"))
        self.le_hz_max = _le(8000, 60); self.le_hz_max.setPlaceholderText("máx")
        self.le_hz_max.editingFinished.connect(self._on_hz_range_changed)
        r1.addWidget(self.le_hz_max)
        body.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(5)
        r2.addWidget(QLabel("VAD(dBSPL):"))
        self.le_threshold = _le(30, 48)
        r2.addWidget(self.le_threshold)
        r2.addSpacing(6)
        r2.addWidget(QLabel("Ref Az:"))
        self.le_ref_az = _le(0, 48)
        r2.addWidget(self.le_ref_az)
        r2.addWidget(QLabel("θ:"))
        self.le_ref_th = _le(0, 48)
        r2.addWidget(self.le_ref_th)
        body.addLayout(r2)

        body.addStretch()

        self.btn_compute = QPushButton("Calcular directividad")
        self.btn_compute.setObjectName("btn_primary")
        self.btn_compute.setEnabled(False)
        self.btn_compute.clicked.connect(self._on_compute)
        body.addWidget(self.btn_compute)

        return w

    def _rg_nota(self) -> QWidget:
        w, body = _dir_group("NOTA")
        body.addStretch()
        self.combo_nota = QComboBox(); self.combo_nota.setFixedWidth(130)
        self.combo_nota.addItem("Todo el audio")
        self.combo_nota.currentTextChanged.connect(self._on_nota_changed)
        body.addWidget(self.combo_nota)
        body.addStretch()
        return w

    def _rg_display(self) -> QWidget:
        w, body = _dir_group("VISUALIZACIÓN")

        r1 = QHBoxLayout(); r1.setSpacing(5)
        r1.addWidget(QLabel("Colorscale:"))
        self.combo_cs = QComboBox(); self.combo_cs.setFixedWidth(90)
        self.combo_cs.addItems(list(COLORSCALES.keys()))
        self.combo_cs.setCurrentText("Plasma")
        self.combo_cs.currentTextChanged.connect(self._on_colorscale_changed)
        r1.addWidget(self.combo_cs)
        r1.addSpacing(6)
        r1.addWidget(QLabel("Elev:"))
        self.combo_el = QComboBox(); self.combo_el.setFixedWidth(90)
        self.combo_el.addItem("Auto (0°)")
        self.combo_el.currentIndexChanged.connect(self._on_el_changed)
        r1.addWidget(self.combo_el)
        body.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(10)
        self._view_checks: dict[str, QCheckBox] = {}
        for label, mode in [("3D","3d"),("Esfera","sphere"),("Polar 2D","polar2d"),("Espectro","spectrum")]:
            chk = QCheckBox(label); chk.setChecked(True)
            chk.toggled.connect(lambda checked, m=mode: self._on_view_toggled(m, checked))
            self._view_checks[mode] = chk
            r2.addWidget(chk)
        body.addLayout(r2)

        return w

    def _rg_spectrum(self) -> QWidget:
        w, body = _dir_group("ESPECTRO")

        r1 = QHBoxLayout(); r1.setSpacing(4)
        r1.addWidget(QLabel("Datos:"))
        self.combo_spec_data = QComboBox(); self.combo_spec_data.setFixedWidth(140)
        self.combo_spec_data.addItems(["Crudo (sin igualar)", "Igualado (post-delta)"])
        self.combo_spec_data.currentIndexChanged.connect(lambda _: self._refresh_display())
        r1.addWidget(self.combo_spec_data)
        body.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(4)
        r2.addWidget(QLabel("Vista:"))
        self.combo_spec_view = QComboBox(); self.combo_spec_view.setFixedWidth(140)
        self.combo_spec_view.addItems(["Global (media ± σ)", "0° a 180°"])
        self.combo_spec_view.currentIndexChanged.connect(lambda _: self._refresh_display())
        r2.addWidget(self.combo_spec_view)
        body.addLayout(r2)

        return w

    def _rg_export(self) -> QWidget:
        w, body = _dir_group("EXPORTAR")

        self.btn_save_npz = QPushButton("Guardar .npz")
        self.btn_save_npz.setEnabled(False)
        self.btn_save_npz.clicked.connect(self._on_save_npz)
        body.addWidget(self.btn_save_npz)

        body.addStretch()

        self.lbl_status = QLabel("Sin datos.")
        self.lbl_status.setStyleSheet("color:#4a5070; font-size:7.5pt;")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setFixedWidth(140)
        body.addWidget(self.lbl_status)

        return w

    # ── Panel derecho (vistas) ────────────────────────────────────────────

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

        # Por defecto: todas las vistas visibles en 2×2

        # Tamaños iguales en ambas filas y columnas
        self._views_splitter.setSizes([500, 500])
        self._row_top.setSizes([500, 500])
        self._row_bot.setSizes([500, 500])

        lay.addWidget(self._views_splitter, 1)

        self.band_selector = BandSelectorWidget()
        self.band_selector.band_changed.connect(self._on_band_changed)
        lay.addWidget(self.band_selector)

        return w

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_view_toggled(self, mode: str, visible: bool):
        section = self._sections[mode]
        if visible:
            section.show()
            if self._full_levels is not None:
                self._update_section(mode)
        else:
            section.hide()
        # Usar estado del checkbox (isVisible() falla cuando el padre está oculto)
        top_vis = self._view_checks["3d"].isChecked() or self._view_checks["sphere"].isChecked()
        bot_vis = self._view_checks["polar2d"].isChecked() or self._view_checks["spectrum"].isChecked()
        self._row_top.setVisible(top_vis)
        self._row_bot.setVisible(bot_vis)
        self._update_band_selector_visibility()

    def _on_colorscale_changed(self, name: str):
        for sec in self._sections.values():
            sec.set_colorscale(name)

    def _on_el_changed(self, idx: int):
        self._current_el_idx = None if idx == 0 else idx - 1
        for sec in self._sections.values():
            sec.set_el_index(self._current_el_idx)

    def _on_hz_range_changed(self):
        try:
            hz_min = float(self.le_hz_min.text())
            hz_max = float(self.le_hz_max.text())
            if hz_min < hz_max:
                self._refresh_display()
        except ValueError:
            pass

    def _on_band_changed(self, index: int, hz: float):
        for sec in self._sections.values():
            if sec.isVisible():
                sec.set_band(index)

    def _on_nota_changed(self, nota: str):
        if self._ma is None:
            return
        ma = self._get_current_ma()
        if ma.dir_levels is not None:
            self._show_results(ma)

    def _on_compute(self):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self.btn_compute.setEnabled(False)
        self.lbl_status.setText("Calculando…")
        self._worker = Worker(self._run_compute)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_compute_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_compute(self):
        ma = self._get_current_ma()
        try:
            threshold = float(self.le_threshold.text())
            ref_az    = int(float(self.le_ref_az.text()))
            ref_th    = int(float(self.le_ref_th.text()))
        except ValueError:
            threshold, ref_az, ref_th = 30.0, 0, 0
        ma.compute_directivity(
            bands          = self.combo_bands.currentText(),
            threshold_spl  = threshold,
            ref_azimuth    = ref_az,
            ref_theta_plot = ref_th,
        )
        return ma

    def _on_compute_done(self, ma):
        nota = self.combo_nota.currentText()
        if nota != "Todo el audio" and self._ma.notes:
            self._ma.notes[nota] = ma
        else:
            self._ma = ma
        self._show_results(self._get_current_ma())
        self.btn_compute.setEnabled(True)
        self.btn_save_npz.setEnabled(True)
        self.log.emit("[Directividad] Cómputo completado.")

    def _show_results(self, ma):
        if ma.dir_levels is None:
            return
        thetas_num = [t for t in ma.thetas if t != 'ref']
        theta_idx  = [ma.thetas.index(t) for t in thetas_num]

        self._full_levels   = ma.dir_levels[:, theta_idx, :]
        self._full_azimuths = np.array(ma.angles,  dtype=np.float32)
        self._full_thetas   = np.array(thetas_num, dtype=np.float32)
        self._full_bands    = ma.dir_freqs.astype(np.float32)

        if ('ref' in ma.thetas
                and ma.dir_ref_spl is not None
                and ma.dir_delta    is not None):
            i_ref = ma.thetas.index('ref')
            base  = (ma.dir_levels[0, i_ref, :] + ma.dir_ref_spl).astype(np.float32)
            self._raw_ref_spl = (base[np.newaxis, :] - ma.dir_delta).astype(np.float32)
            self._eq_ref_spl  = base
        elif ma.dir_ref_spl is not None:
            n_az = len(ma.angles)
            self._raw_ref_spl = np.tile(ma.dir_ref_spl, (n_az, 1)).astype(np.float32)
            self._eq_ref_spl  = ma.dir_ref_spl.astype(np.float32)
        else:
            self._raw_ref_spl = None
            self._eq_ref_spl  = None

        self._update_el_combo(self._full_thetas)
        self._refresh_display()
        self.lbl_status.setText(
            f"Dir. calculada — {self._full_levels.shape}  |  "
            f"{ma.dir_freqs[0]:.0f}–{ma.dir_freqs[-1]:.0f} Hz"
        )

    def _refresh_display(self):
        if self._full_levels is None:
            return
        try:
            hz_min = float(self.le_hz_min.text())
            hz_max = float(self.le_hz_max.text())
        except ValueError:
            hz_min, hz_max = 200.0, 8000.0

        mask = (self._full_bands >= hz_min) & (self._full_bands <= hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)

        f_levels = self._full_levels[:, :, mask]
        f_bands  = self._full_bands[mask]

        data_idx    = self.combo_spec_data.currentIndex()
        spec_global = (self.combo_spec_view.currentIndex() == 0)

        if self._raw_ref_spl is not None:
            if data_idx == 0:
                f_ref = self._raw_ref_spl[:, mask]
            else:
                n_az  = self._raw_ref_spl.shape[0]
                f_ref = np.tile(self._eq_ref_spl[mask], (n_az, 1))
        else:
            f_ref = None

        self.band_selector.set_bands(f_bands)

        kwargs = dict(
            levels       = f_levels,
            azimuths     = self._full_azimuths,
            elevations   = self._full_thetas,
            bands        = f_bands,
            band_index   = 0,
            ref_spectrum = f_ref,
            spec_global  = spec_global,
        )
        for mode, sec in self._sections.items():
            if sec.isVisible():
                sec.set_data(**kwargs)
                if self._current_el_idx is not None:
                    sec.set_el_index(self._current_el_idx)

    def _update_section(self, mode: str):
        """Actualiza solo la sección indicada con los datos actuales."""
        if self._full_levels is None:
            return
        try:
            hz_min = float(self.le_hz_min.text())
            hz_max = float(self.le_hz_max.text())
        except ValueError:
            hz_min, hz_max = 200.0, 8000.0

        mask = (self._full_bands >= hz_min) & (self._full_bands <= hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)

        f_levels = self._full_levels[:, :, mask]
        f_bands  = self._full_bands[mask]

        data_idx    = self.combo_spec_data.currentIndex()
        spec_global = (self.combo_spec_view.currentIndex() == 0)
        if self._raw_ref_spl is not None:
            f_ref = (self._raw_ref_spl[:, mask] if data_idx == 0
                     else np.tile(self._eq_ref_spl[mask],
                                  (self._raw_ref_spl.shape[0], 1)))
        else:
            f_ref = None

        sec = self._sections[mode]
        sec.set_data(
            levels       = f_levels,
            azimuths     = self._full_azimuths,
            elevations   = self._full_thetas,
            bands        = f_bands,
            band_index   = 0,
            ref_spectrum = f_ref,
            spec_global  = spec_global,
        )
        if self._current_el_idx is not None:
            sec.set_el_index(self._current_el_idx)

    def _update_el_combo(self, thetas: np.ndarray):
        self.combo_el.blockSignals(True)
        self.combo_el.clear()
        self.combo_el.addItem("Auto (0°)")
        for t in thetas:
            self.combo_el.addItem(f"{t:.0f}°")
        self.combo_el.blockSignals(False)

    def _update_band_selector_visibility(self):
        any_non_spectrum = any(
            self._view_checks[mode].isChecked()
            for mode in ("3d", "sphere", "polar2d")
        )
        self.band_selector.setVisible(any_non_spectrum)

    def _get_current_ma(self):
        nota = self.combo_nota.currentText()
        if nota != "Todo el audio" and self._ma and self._ma.notes:
            return self._ma.notes.get(nota, self._ma)
        return self._ma

    def _on_save_npz(self):
        if self._ma is None or self._ma.dir_levels is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar resultados", "", "NPZ (*.npz)"
        )
        if not path:
            return
        try:
            save_results(
                filepath       = path,
                ma             = self._ma,
                bands          = self.combo_bands.currentText(),
                threshold_spl  = float(self.le_threshold.text() or 30),
                ref_azimuth    = int(float(self.le_ref_az.text() or 0)),
                ref_theta_plot = int(float(self.le_ref_th.text() or 0)),
            )
            self.log.emit(f"[Directividad] Guardado → {path}")
        except Exception as e:
            self.log.emit(f"[ERROR] Al guardar: {e}")

    def _on_error(self, msg: str):
        self.btn_compute.setEnabled(True)
        self.lbl_status.setText("Error en el cómputo.")
        self.log.emit(f"[ERROR]\n{msg}")

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma = ma
        self.btn_compute.setEnabled(ma._is_spl)

        self.combo_nota.blockSignals(True)
        self.combo_nota.clear()
        self.combo_nota.addItem("Todo el audio")
        if ma.notes:
            for nota in ma.notes:
                self.combo_nota.addItem(nota)
        self.combo_nota.blockSignals(False)

        if not ma._is_spl:
            self.lbl_status.setText(
                "Necesitás calibrar y convertir a SPL antes de calcular."
            )
        else:
            self.lbl_status.setText("Tensor listo. Presioná 'Calcular directividad'.")

        if ma.dir_levels is not None:
            self._show_results(ma)
            self.btn_save_npz.setEnabled(True)


# ── Helpers de construcción del Ribbon ────────────────────────────────────────

def _dir_group(title: str) -> tuple[QWidget, QVBoxLayout]:
    outer = QWidget()
    vlay = QVBoxLayout(outer)
    vlay.setContentsMargins(10, 4, 10, 2)
    vlay.setSpacing(3)

    body = QVBoxLayout()
    body.setSpacing(3)
    vlay.addLayout(body, 1)

    lbl = QLabel(title)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        "color:#4a5070; font-size:7.5pt; background:transparent; border:none;"
    )
    vlay.addWidget(lbl)
    return outer, body


def _dir_vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet("color: #2a2d3e;")
    sep.setFixedWidth(1)
    return sep
