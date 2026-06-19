"""
ui/tab_directividad.py — Tab 4: Cómputo de directividad y visualización.
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox,
    QComboBox, QFileDialog, QScrollArea, QFrame,
    QButtonGroup,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.worker import Worker
from core.data_store import save_results
from ui.balloon_view import BalloonView
from ui.band_selector import BandSelectorWidget
from plot.balloon import COLORSCALES


class TabDirectividad(QWidget):
    """
    Tab de directividad y visualización.
    Señales:
        log(str)
    """
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma          = None
        self._worker: Worker | None = None
        # Datos completos sin filtrar (se filtran al mostrar)
        self._full_levels    = None
        self._full_azimuths  = None
        self._full_thetas    = None
        self._full_bands     = None
        self._raw_ref_spl    = None   # (n_az, n_bands) SPL crudo del mic ref por azimuth
        self._eq_ref_spl     = None   # (n_bands,)      SPL igualado (post-delta, constante)
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_left_panel())

        # Panel derecho: toolbar de vista + balloon + band selector
        right     = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        right_lay.setSpacing(6)

        right_lay.addWidget(self._make_view_toolbar())

        self.balloon = BalloonView()
        right_lay.addWidget(self.balloon, 1)

        self.band_selector = BandSelectorWidget()
        self.band_selector.band_changed.connect(self._on_band_changed)
        right_lay.addWidget(self.band_selector)

        root.addWidget(right, 1)

    def _make_view_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet("""
            QWidget { background: #12141e; border-bottom: 1px solid #2a2d3e; }
        """)
        lay = QHBoxLayout(toolbar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)

        lay.addWidget(QLabel("Vista:"))

        self._view_btn_group = QButtonGroup(self)
        self._view_btn_group.setExclusive(True)

        btn_style = """
            QPushButton {
                background: #1e2134; border: 1px solid #3a3d55;
                border-radius: 4px; color: #8892b0;
                padding: 3px 12px; font-size: 9pt;
            }
            QPushButton:checked {
                background: #3d4580; border-color: #5865a0; color: #e8ecf4;
            }
            QPushButton:hover { background: #2a2d45; }
        """

        for label, mode in [("Superficie 3D", "3d"), ("Esfera", "sphere"),
                             ("Polar 2D", "polar2d"), ("Espectro", "spectrum")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(btn_style)
            btn.setProperty("view_mode", mode)
            self._view_btn_group.addButton(btn)
            lay.addWidget(btn)

        # Activar "Globo 3D" por defecto
        self._view_btn_group.buttons()[0].setChecked(True)
        self._view_btn_group.buttonClicked.connect(self._on_view_mode_changed)

        lay.addStretch()
        return toolbar

    def _make_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(300)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(14)

        lay.addWidget(self._make_group_compute())
        lay.addWidget(self._make_group_nota())
        lay.addWidget(self._make_group_display())
        lay.addWidget(self._make_group_export())
        lay.addWidget(self._make_status())
        lay.addStretch()

        scroll.setWidget(container)
        return scroll

    def _make_group_compute(self) -> QGroupBox:
        g = QGroupBox("CÓMPUTO")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        def spin_row(label, widget):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addStretch()
            row.addWidget(widget)
            lay.addLayout(row)

        self.combo_bands = QComboBox()
        self.combo_bands.addItems(["1/3", "octave"])
        spin_row("Bandas:", self.combo_bands)

        # Rango de frecuencias a mostrar
        hz_row = QHBoxLayout()
        hz_row.addWidget(QLabel("Hz mín:"))
        self.spin_hz_min = QSpinBox()
        self.spin_hz_min.setRange(20, 20000)
        self.spin_hz_min.setValue(200)
        self.spin_hz_min.setSingleStep(100)
        self.spin_hz_min.setFixedWidth(75)
        hz_row.addWidget(self.spin_hz_min)
        hz_row.addSpacing(8)
        hz_row.addWidget(QLabel("máx:"))
        self.spin_hz_max = QSpinBox()
        self.spin_hz_max.setRange(20, 20000)
        self.spin_hz_max.setValue(8000)
        self.spin_hz_max.setSingleStep(100)
        self.spin_hz_max.setFixedWidth(75)
        hz_row.addWidget(self.spin_hz_max)
        lay.addLayout(hz_row)
        self.spin_hz_min.valueChanged.connect(self._on_hz_range_changed)
        self.spin_hz_max.valueChanged.connect(self._on_hz_range_changed)

        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0, 80)
        self.spin_threshold.setValue(30)
        self.spin_threshold.setSuffix(" dB SPL")
        self.spin_threshold.setFixedWidth(100)
        spin_row("Umbral VAD:", self.spin_threshold)

        self.spin_ref_az = QSpinBox()
        self.spin_ref_az.setRange(0, 359)
        self.spin_ref_az.setValue(0)
        self.spin_ref_az.setSuffix("°")
        self.spin_ref_az.setFixedWidth(70)
        spin_row("Ref azimuth:", self.spin_ref_az)

        self.spin_ref_th = QSpinBox()
        self.spin_ref_th.setRange(0, 180)
        self.spin_ref_th.setValue(0)
        self.spin_ref_th.setSuffix("°")
        self.spin_ref_th.setFixedWidth(70)
        spin_row("Ref theta plot:", self.spin_ref_th)

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
        self.combo_cs.currentTextChanged.connect(
            lambda name: self.balloon.set_colorscale(name)
        )
        lay.addWidget(self.combo_cs)

        # Selector de elevación para Polar 2D y Espectro
        lay.addWidget(QLabel("Elevación (2D/Espectro):"))
        self.combo_el = QComboBox()
        self.combo_el.addItem("Automático (0°)")
        self.combo_el.currentIndexChanged.connect(self._on_el_changed)
        lay.addWidget(self.combo_el)

        # Controles específicos del espectro
        lay.addWidget(QLabel("Espectro — datos:"))
        self.combo_spec_data = QComboBox()
        self.combo_spec_data.addItems(["Crudo (sin igualar)", "Igualado (post-delta)"])
        self.combo_spec_data.currentIndexChanged.connect(lambda _: self._refresh_display())
        lay.addWidget(self.combo_spec_data)

        lay.addWidget(QLabel("Espectro — vista:"))
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

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_view_mode_changed(self, btn):
        mode = btn.property("view_mode")
        self.balloon.set_view_mode(mode)
        # El band selector solo aplica a vistas por banda
        self.band_selector.setVisible(mode != "spectrum")

    def _on_hz_range_changed(self):
        hz_min = float(self.spin_hz_min.value())
        hz_max = float(self.spin_hz_max.value())
        if hz_min < hz_max:
            self._refresh_display()

    def _on_el_changed(self, idx):
        # idx=0 → automático (None), idx>0 → elevación específica
        if idx == 0:
            self.balloon.set_el_index(None)
        else:
            self.balloon.set_el_index(idx - 1)

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
        ma        = self._get_current_ma()
        bands     = self.combo_bands.currentText()
        threshold = self.spin_threshold.value()
        ref_az    = self.spin_ref_az.value()
        ref_th    = self.spin_ref_th.value()
        ma.compute_directivity(
            bands          = bands,
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

        # Guardar datos completos para filtrar en _refresh_display()
        dir_lev = ma.dir_levels[:, theta_idx, :]          # (n_az, n_th, n_bands) relativo
        self._full_levels   = dir_lev
        self._full_azimuths = np.array(ma.angles,  dtype=np.float32)
        self._full_thetas   = np.array(thetas_num, dtype=np.float32)
        self._full_bands    = ma.dir_freqs.astype(np.float32)

        # SPL del mic de referencia por azimuth:
        #   base = spl_levels[0, i_ref, :] = dir_levels[0, i_ref, :] + dir_ref_spl
        #   crudo[i_az, :] = base - dir_delta[i_az, :]   (antes de igualar)
        #   igualado = base                               (constante, post-delta)
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

        # Actualizar combo de elevaciones con todos los thetas disponibles
        self._update_el_combo(self._full_thetas)

        self._refresh_display()
        self.lbl_status.setText(
            f"Dir. calculada — {self._full_levels.shape}  |  "
            f"{ma.dir_freqs[0]:.0f}–{ma.dir_freqs[-1]:.0f} Hz"
        )

    def _refresh_display(self):
        """Aplica el filtro de Hz y actualiza band_selector + balloon_view."""
        if self._full_levels is None:
            return
        hz_min = float(self.spin_hz_min.value())
        hz_max = float(self.spin_hz_max.value())
        mask = (self._full_bands >= hz_min) & (self._full_bands <= hz_max)
        if not mask.any():
            mask = np.ones(len(self._full_bands), dtype=bool)

        f_levels = self._full_levels[:, :, mask]
        f_bands  = self._full_bands[mask]

        # Datos de espectro del mic de referencia
        data_idx    = self.combo_spec_data.currentIndex()   # 0=Crudo, 1=Igualado
        spec_global = (self.combo_spec_view.currentIndex() == 0)

        if self._raw_ref_spl is not None:
            if data_idx == 0:   # Crudo: SPL por azimuth antes del delta
                f_ref = self._raw_ref_spl[:, mask]
            else:               # Igualado: valor constante post-delta
                n_az  = self._raw_ref_spl.shape[0]
                f_ref = np.tile(self._eq_ref_spl[mask], (n_az, 1))
        else:
            f_ref = None

        self.band_selector.set_bands(f_bands)
        self.balloon.set_data(
            levels       = f_levels,
            azimuths     = self._full_azimuths,
            elevations   = self._full_thetas,
            bands        = f_bands,
            band_index   = 0,
            ref_spectrum = f_ref,
            spec_global  = spec_global,
        )

    def _update_el_combo(self, thetas: np.ndarray):
        self.combo_el.blockSignals(True)
        self.combo_el.clear()
        self.combo_el.addItem("Automático (0°)")
        for t in thetas:
            self.combo_el.addItem(f"{t:.0f}°")
        self.combo_el.blockSignals(False)

    def _on_band_changed(self, index: int, hz: float):
        self.balloon.set_band(index)

    def _on_nota_changed(self, nota: str):
        if self._ma is None:
            return
        ma = self._get_current_ma()
        if ma.dir_levels is not None:
            self._show_results(ma)

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
                threshold_spl  = self.spin_threshold.value(),
                ref_azimuth    = self.spin_ref_az.value(),
                ref_theta_plot = self.spin_ref_th.value(),
            )
            self.log.emit(f"[Directividad] Guardado → {path}")
        except Exception as e:
            self.log.emit(f"[ERROR] Al guardar: {e}")

    def _on_error(self, msg: str):
        self.btn_compute.setEnabled(True)
        self.lbl_status.setText("Error en el cómputo.")
        self.log.emit(f"[ERROR]\n{msg}")

    # ── API pública ───────────────────────────────────────────────────────────

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
