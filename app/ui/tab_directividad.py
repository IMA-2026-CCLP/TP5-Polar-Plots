"""
ui/tab_directividad.py — Tab Directividad: cómputo y visualización multi-panel.
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit,
    QComboBox, QFileDialog, QScrollArea, QFrame,
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

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = self._make_left_panel()
        left.setMinimumWidth(200)
        splitter.addWidget(left)
        splitter.addWidget(self._make_right_panel())
        splitter.setSizes([280, 900])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

    # ── Panel izquierdo ───────────────────────────────────────────────────

    def _make_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(14)

        lay.addWidget(self._make_group_compute())
        lay.addWidget(self._make_group_nota())
        lay.addWidget(self._make_group_display())
        lay.addWidget(self._make_group_spectrum())
        lay.addWidget(self._make_group_export())
        lay.addWidget(self._make_status())
        lay.addStretch()

        scroll.setWidget(container)
        return scroll

    def _make_group_compute(self) -> QGroupBox:
        g = QGroupBox("CÓMPUTO")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        def row(label, widget):
            r = QHBoxLayout()
            r.addWidget(QLabel(label))
            r.addStretch()
            r.addWidget(widget)
            lay.addLayout(r)

        self.combo_bands = QComboBox()
        self.combo_bands.addItems(["1/3", "octave"])
        row("Bandas:", self.combo_bands)

        hz_row = QHBoxLayout()
        hz_row.addWidget(QLabel("Hz mín:"))
        self.le_hz_min = _le(200, 68)
        hz_row.addWidget(self.le_hz_min)
        hz_row.addSpacing(4)
        hz_row.addWidget(QLabel("máx:"))
        self.le_hz_max = _le(8000, 68)
        hz_row.addWidget(self.le_hz_max)
        lay.addLayout(hz_row)
        self.le_hz_min.editingFinished.connect(self._on_hz_range_changed)
        self.le_hz_max.editingFinished.connect(self._on_hz_range_changed)

        self.le_threshold = _le(30, 90, "dB SPL")
        row("Umbral VAD:", self.le_threshold)

        self.le_ref_az = _le(0, 70, "°")
        row("Ref azimuth:", self.le_ref_az)

        self.le_ref_th = _le(0, 70, "°")
        row("Ref theta plot:", self.le_ref_th)

        self.btn_compute = QPushButton("Calcular directividad")
        self.btn_compute.setObjectName("btn_primary")
        self.btn_compute.setEnabled(False)
        self.btn_compute.clicked.connect(self._on_compute)
        lay.addWidget(self.btn_compute)

        return g

    def _make_group_nota(self) -> QGroupBox:
        g = QGroupBox("NOTA")
        lay = QVBoxLayout(g)
        self.combo_nota = QComboBox()
        self.combo_nota.addItem("Todo el audio")
        self.combo_nota.currentTextChanged.connect(self._on_nota_changed)
        lay.addWidget(self.combo_nota)
        return g

    def _make_group_display(self) -> QGroupBox:
        g = QGroupBox("VISUALIZACIÓN")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Colorscale:"))
        self.combo_cs = QComboBox()
        self.combo_cs.addItems(list(COLORSCALES.keys()))
        self.combo_cs.setCurrentText("Plasma")
        self.combo_cs.currentTextChanged.connect(self._on_colorscale_changed)
        lay.addWidget(self.combo_cs)

        lay.addWidget(QLabel("Elevación (2D/Espectro):"))
        self.combo_el = QComboBox()
        self.combo_el.addItem("Automático (0°)")
        self.combo_el.currentIndexChanged.connect(self._on_el_changed)
        lay.addWidget(self.combo_el)

        lay.addWidget(QLabel("Vistas activas:"))
        self._view_checks: dict[str, QCheckBox] = {}
        for label, mode in [
            ("Superficie 3D", "3d"),
            ("Esfera",        "sphere"),
            ("Polar 2D",      "polar2d"),
            ("Espectro",      "spectrum"),
        ]:
            chk = QCheckBox(label)
            chk.setChecked(mode == "3d")
            chk.toggled.connect(lambda checked, m=mode: self._on_view_toggled(m, checked))
            self._view_checks[mode] = chk
            lay.addWidget(chk)

        return g

    def _make_group_spectrum(self) -> QGroupBox:
        g = QGroupBox("ESPECTRO")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Datos:"))
        self.combo_spec_data = QComboBox()
        self.combo_spec_data.addItems(["Crudo (sin igualar)", "Igualado (post-delta)"])
        self.combo_spec_data.currentIndexChanged.connect(lambda _: self._refresh_display())
        lay.addWidget(self.combo_spec_data)

        lay.addWidget(QLabel("Vista:"))
        self.combo_spec_view = QComboBox()
        self.combo_spec_view.addItems(["Global (media ± σ)", "0° a 180°"])
        self.combo_spec_view.currentIndexChanged.connect(lambda _: self._refresh_display())
        lay.addWidget(self.combo_spec_view)

        return g

    def _make_group_export(self) -> QGroupBox:
        g = QGroupBox("EXPORTAR")
        lay = QVBoxLayout(g)
        self.btn_save_npz = QPushButton("Guardar resultados .npz")
        self.btn_save_npz.setEnabled(False)
        self.btn_save_npz.clicked.connect(self._on_save_npz)
        lay.addWidget(self.btn_save_npz)
        return g

    def _make_status(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_status = QLabel("Sin datos de directividad.")
        self.lbl_status.setObjectName("label_hint")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        return w

    # ── Panel derecho (vistas) ────────────────────────────────────────────

    def _make_right_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # Splitter vertical con las 4 vistas
        self._views_splitter = QSplitter(Qt.Orientation.Vertical)
        self._views_splitter.setChildrenCollapsible(True)

        self._sections: dict[str, _ViewSection] = {
            "3d":       _ViewSection("Superficie 3D", "3d"),
            "sphere":   _ViewSection("Esfera",        "sphere"),
            "polar2d":  _ViewSection("Polar 2D",      "polar2d"),
            "spectrum": _ViewSection("Espectro",      "spectrum"),
        }
        for section in self._sections.values():
            self._views_splitter.addWidget(section)
            section.hide()

        self._sections["3d"].show()   # solo 3D activo por defecto

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
        # band_selector solo cuando hay alguna vista no-espectro visible
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
        self.combo_el.addItem("Automático (0°)")
        for t in thetas:
            self.combo_el.addItem(f"{t:.0f}°")
        self.combo_el.blockSignals(False)

    def _update_band_selector_visibility(self):
        any_non_spectrum = any(
            sec.isVisible()
            for mode, sec in self._sections.items()
            if mode != "spectrum"
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
