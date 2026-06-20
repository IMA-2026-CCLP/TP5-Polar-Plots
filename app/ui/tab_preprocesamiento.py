"""
ui/tab_preprocesamiento.py — Tab 2: Visualización de señales + preprocesamiento.

Muestra las formas de onda del tensor y permite aplicar HPF,
alineamiento de tomas y alineamiento a referencia, actualizando
el gráfico inmediatamente tras cada operación.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QCheckBox, QLineEdit,
    QSplitter, QScrollArea, QFrame, QSizePolicy,
)
import os
import tempfile

from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from core.worker import Worker
from plot.waveform import build_waveform_html, build_rms_html


class TabPreprocesamiento(QWidget):
    """
    Señales:
        ma_updated(object) — emite el MicArray tras cada operación
        log(str)
    """
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma          = None
        self._worker: Worker | None = None
        self._plot_workers: list[Worker] = []   # evita GC prematuro
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Panel izquierdo de controles
        ctrl_panel = self._make_ctrl_panel()
        ctrl_panel.setMinimumWidth(200)

        # Vista web — permitir que file:// cargue recursos remotos (CDN de Plotly)
        self._web = QWebEngineView()
        self._web.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._web.setStyleSheet("background:#1a1d27;")
        self._plot_tmp: str | None = None

        splitter.addWidget(ctrl_panel)
        splitter.addWidget(self._web)
        splitter.setSizes([280, 900])   # ancho inicial
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

    def _make_ctrl_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(12, 16, 12, 16)
        lay.setSpacing(12)

        lay.addWidget(self._make_group_vista())
        lay.addWidget(self._make_group_hpf())
        lay.addWidget(self._make_group_align_takes())
        lay.addWidget(self._make_group_align_ref())
        lay.addStretch()

        scroll.setWidget(container)
        return scroll

    # ── Grupos de controles ───────────────────────────────────────────────

    def _make_group_vista(self) -> QGroupBox:
        g = QGroupBox("VISUALIZACIÓN")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        # Tipo de gráfico
        lay.addWidget(QLabel("Tipo:"))
        self.combo_tipo = QComboBox()
        self.combo_tipo.addItems(["Formas de onda", "RMS por toma"])
        self.combo_tipo.currentIndexChanged.connect(self._on_tipo_changed)
        lay.addWidget(self.combo_tipo)

        # Theta
        self.lbl_theta = QLabel("Theta (mic):")
        lay.addWidget(self.lbl_theta)
        self.combo_theta = QComboBox()
        lay.addWidget(self.combo_theta)

        # Azimuth
        self.lbl_az = QLabel("Azimuth (toma):")
        lay.addWidget(self.lbl_az)
        self.combo_az = QComboBox()
        lay.addWidget(self.combo_az)

        # Opciones de señal
        self.chk_envelope = QCheckBox("Envolvente")
        self.chk_envelope.setChecked(True)
        lay.addWidget(self.chk_envelope)

        self.chk_db = QCheckBox("En dB")
        # Al activar dB, forzar envolvente (señal cruda en dB no tiene sentido)
        self.chk_db.toggled.connect(self._on_db_toggled)
        lay.addWidget(self.chk_db)

        # Rango eje Y
        self.chk_yrange = QCheckBox("Fijar eje Y")
        self.chk_yrange.setChecked(False)
        self.chk_yrange.toggled.connect(self._on_yrange_toggled)
        lay.addWidget(self.chk_yrange)

        yrow_min = QHBoxLayout()
        self.lbl_ymin = QLabel("  Y mín:")
        self.spin_ymin = QLineEdit("-60")
        self.spin_ymin.setFixedWidth(70)
        self.spin_ymin.setEnabled(False)
        self.spin_ymin.wheelEvent = lambda e: e.ignore()
        yrow_min.addWidget(self.lbl_ymin)
        yrow_min.addWidget(self.spin_ymin)
        lay.addLayout(yrow_min)

        yrow_max = QHBoxLayout()
        self.lbl_ymax = QLabel("  Y máx:")
        self.spin_ymax = QLineEdit("0")
        self.spin_ymax.setFixedWidth(70)
        self.spin_ymax.setEnabled(False)
        self.spin_ymax.wheelEvent = lambda e: e.ignore()
        yrow_max.addWidget(self.lbl_ymax)
        yrow_max.addWidget(self.spin_ymax)
        lay.addLayout(yrow_max)

        btn = QPushButton("Actualizar gráfico")
        btn.setObjectName("btn_primary")
        btn.clicked.connect(self._refresh_plot)
        lay.addWidget(btn)

        return g

    def _make_group_hpf(self) -> QGroupBox:
        g = QGroupBox("HIGH-PASS FILTER")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Corte (Hz):"))
        self.spin_hpf = QLineEdit("200")
        self.spin_hpf.setFixedWidth(80)
        self.spin_hpf.wheelEvent = lambda e: e.ignore()
        row.addWidget(self.spin_hpf)
        lay.addLayout(row)

        btn = QPushButton("Aplicar HPF")
        btn.clicked.connect(self._on_apply_hpf)
        lay.addWidget(btn)

        lbl = QLabel("Filtra y actualiza el gráfico.")
        lbl.setObjectName("label_hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        return g

    def _make_group_align_takes(self) -> QGroupBox:
        g = QGroupBox("ALINEAR TOMAS")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Onset target (s):"))
        self.spin_onset = QLineEdit("1.0")
        self.spin_onset.setFixedWidth(70)
        self.spin_onset.wheelEvent = lambda e: e.ignore()
        row1.addWidget(self.spin_onset)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Umbral (dBFS):"))
        self.spin_thresh = QLineEdit("-40")
        self.spin_thresh.setFixedWidth(70)
        self.spin_thresh.wheelEvent = lambda e: e.ignore()
        row2.addWidget(self.spin_thresh)
        lay.addLayout(row2)

        lay.addWidget(QLabel("Theta de referencia:"))
        self.combo_align_theta = QComboBox()
        lay.addWidget(self.combo_align_theta)

        btn = QPushButton("Alinear tomas")
        btn.clicked.connect(self._on_align_takes)
        lay.addWidget(btn)

        lbl = QLabel("Alinea onsets al target y actualiza el gráfico.")
        lbl.setObjectName("label_hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        return g

    def _make_group_align_ref(self) -> QGroupBox:
        g = QGroupBox("ALINEAR A REFERENCIA")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        lbl = QLabel("Alinea todas las thetas a la referencia usando GCC-PHAT.")
        lbl.setObjectName("label_hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        btn = QPushButton("Alinear a referencia")
        btn.clicked.connect(self._on_align_ref)
        lay.addWidget(btn)

        return g

    # ── Slots de UI ───────────────────────────────────────────────────────

    def _on_yrange_toggled(self, checked: bool):
        self.spin_ymin.setEnabled(checked)
        self.spin_ymax.setEnabled(checked)

    def _on_db_toggled(self, checked: bool):
        if checked:
            self.chk_envelope.setChecked(True)
            self.chk_envelope.setEnabled(False)   # no tiene sentido desactivarla
        else:
            self.chk_envelope.setEnabled(True)

    def _on_tipo_changed(self):
        is_waveform = self.combo_tipo.currentIndex() == 0
        self.lbl_theta.setVisible(is_waveform)
        self.combo_theta.setVisible(is_waveform)
        self.lbl_az.setVisible(is_waveform)
        self.combo_az.setVisible(is_waveform)
        self.chk_envelope.setVisible(is_waveform)
        self.chk_db.setVisible(is_waveform)
        self._refresh_plot()

    def _refresh_plot(self):
        if self._ma is None:
            return
        # Parámetros capturados en el UI thread antes de ir al worker
        tipo    = self.combo_tipo.currentIndex()
        theta   = self._parse_theta(self.combo_theta.currentText()) if tipo == 0 else None
        az_text = self.combo_az.currentText() if tipo == 0 else None
        azimuth = None if (az_text is None or az_text == "Todos") else int(az_text.rstrip("°"))
        env     = self.chk_envelope.isChecked()
        db      = self.chk_db.isChecked()
        try:
            yrange = ([float(self.spin_ymin.text()), float(self.spin_ymax.text())]
                      if self.chk_yrange.isChecked() else None)
        except ValueError:
            yrange = None
        ma      = self._ma   # referencia local

        def _build():
            if tipo == 1:
                return build_rms_html(ma, yrange=yrange)
            return build_waveform_html(ma, theta=theta, azimuth=azimuth,
                                       envelope=env, dB=db, yrange=yrange)

        def _set_html(html: str):
            if self._plot_tmp is None:
                fd, path = tempfile.mkstemp(suffix=".html", prefix="ppanalyzer_")
                os.close(fd)
                self._plot_tmp = path
            with open(self._plot_tmp, "w", encoding="utf-8") as f:
                f.write(html)
            self._web.setUrl(QUrl.fromLocalFile(self._plot_tmp))

        w = Worker(_build)
        w.finished.connect(_set_html)
        w.error.connect(lambda msg: self.log.emit(f"[Plot error] {msg}"))
        # limpiar workers terminados y guardar el nuevo para evitar GC prematuro
        self._plot_workers = [x for x in self._plot_workers if x.isRunning()]
        self._plot_workers.append(w)
        w.start()

    # ── Operaciones ───────────────────────────────────────────────────────

    def _on_apply_hpf(self):
        if self._ma is None or self._busy():
            return
        try:
            hz = float(self.spin_hpf.text())
        except ValueError:
            hz = 200.0
        self.log.emit(f"[Preprocesamiento] Aplicando HPF {hz:.0f} Hz…")
        self._worker = Worker(lambda: self._run_hpf(hz))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_hpf(self, hz):
        self._ma.hpf(hz)
        return self._ma

    def _on_align_takes(self):
        if self._ma is None or self._busy():
            return
        try:
            onset  = float(self.spin_onset.text())
            thresh = float(self.spin_thresh.text())
        except ValueError:
            onset, thresh = 1.0, -40.0
        theta  = self._parse_theta(self.combo_align_theta.currentText())
        self.log.emit(f"[Preprocesamiento] Alineando tomas (onset={onset}s, θ={theta})…")
        self._worker = Worker(lambda: self._run_align_takes(onset, thresh, theta))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_align_takes(self, onset, thresh, theta):
        self._ma.align_takes(target_onset=onset, theta=theta, threshold_dB=thresh)
        return self._ma

    def _on_align_ref(self):
        if self._ma is None or self._busy():
            return
        self.log.emit("[Preprocesamiento] Alineando a referencia (GCC-PHAT)…")
        self._worker = Worker(lambda: self._run_align_ref())
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_align_ref(self):
        self._ma.align_to_ref()
        return self._ma

    def _on_op_done(self, ma):
        self._ma = ma
        self._refresh_plot()
        self.ma_updated.emit(ma)
        self.log.emit("[Preprocesamiento] Listo.")

    def _on_error(self, msg: str):
        self.log.emit(f"[ERROR]\n{msg}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _parse_theta(self, text: str):
        if text == "ref":
            return 'ref'
        return int(text.rstrip("°"))

    def _populate_combos(self):
        """Rellena los QComboBox con los valores del MicArray actual."""
        self.combo_theta.blockSignals(True)
        self.combo_az.blockSignals(True)
        self.combo_align_theta.blockSignals(True)

        self.combo_theta.clear()
        self.combo_az.clear()
        self.combo_align_theta.clear()

        for th in self._ma.thetas:
            label = "ref" if th == 'ref' else f"{th}°"
            self.combo_theta.addItem(label)
            self.combo_align_theta.addItem(label)

        # Selección por defecto: 'ref' si existe
        ref_idx = next((i for i, th in enumerate(self._ma.thetas) if th == 'ref'), 0)
        self.combo_theta.setCurrentIndex(ref_idx)
        self.combo_align_theta.setCurrentIndex(ref_idx)

        self.combo_az.addItem("Todos")
        for az in self._ma.angles:
            self.combo_az.addItem(f"{az}°")

        self.combo_theta.blockSignals(False)
        self.combo_az.blockSignals(False)
        self.combo_align_theta.blockSignals(False)

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma = ma
        self._populate_combos()
        self._on_tipo_changed()   # también llama _refresh_plot
