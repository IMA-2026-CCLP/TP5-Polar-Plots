"""
ui/tab_preprocesamiento.py — Tab Preprocesamiento con Ribbon horizontal.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QCheckBox, QLineEdit, QFrame,
)
import os
import tempfile

from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from core.worker import Worker
from plot.waveform import build_waveform_html, build_rms_html


_RIBBON_H = 100   # altura fija del ribbon en px

_RIBBON_STYLE = """
    QWidget#ribbon {
        background: #161829;
        border-bottom: 1px solid #2a2d3e;
    }
    QWidget#ribbon QLabel {
        color: #8892b0;
        font-size: 8pt;
    }
    QWidget#ribbon QPushButton {
        background: #1e2134;
        border: 1px solid #3a3d55;
        border-radius: 4px;
        color: #c8d0e8;
        font-size: 8pt;
        padding: 3px 8px;
        min-height: 20px;
    }
    QWidget#ribbon QPushButton:hover  { background: #2a2d45; }
    QWidget#ribbon QPushButton:pressed{ background: #12141e; }
    QWidget#ribbon QPushButton#btn_primary {
        background: #3d4f9f;
        border-color: #5865c0;
        color: #ffffff;
    }
    QWidget#ribbon QPushButton#btn_primary:hover { background: #4a5db8; }
    QWidget#ribbon QComboBox {
        background: #1e2134;
        border: 1px solid #3a3d55;
        border-radius: 3px;
        color: #c8d0e8;
        font-size: 8pt;
        padding: 2px 4px;
        min-height: 18px;
    }
    QWidget#ribbon QComboBox::drop-down { border: none; width: 14px; }
    QWidget#ribbon QLineEdit {
        background: #1e2134;
        border: 1px solid #3a3d55;
        border-radius: 3px;
        color: #c8d0e8;
        font-size: 8pt;
        padding: 2px 4px;
        min-height: 18px;
    }
    QWidget#ribbon QCheckBox {
        color: #8892b0;
        font-size: 8pt;
        spacing: 4px;
    }
    QWidget#grp_title {
        background: transparent;
        color: #4a5070;
        font-size: 7.5pt;
    }
"""


def _le(default="", width=68) -> QLineEdit:
    w = QLineEdit(str(default))
    w.setFixedWidth(width)
    w.wheelEvent = lambda e: e.ignore()
    return w


class TabPreprocesamiento(QWidget):
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma           = None
        self._worker: Worker | None = None
        self._plot_workers: list[Worker] = []
        self._build_ui()

    # ── Construcción ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_ribbon())

        self._web = QWebEngineView()
        self._web.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._web.setStyleSheet("background:#1a1d27;")
        self._plot_tmp: str | None = None
        root.addWidget(self._web, 1)

    # ── Ribbon ────────────────────────────────────────────────────────────

    def _make_ribbon(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("ribbon")
        bar.setFixedHeight(_RIBBON_H)
        bar.setStyleSheet(_RIBBON_STYLE)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 2)
        lay.setSpacing(0)

        lay.addWidget(self._rg_vista())
        lay.addWidget(_vsep())
        lay.addWidget(self._rg_hpf())
        lay.addWidget(_vsep())
        lay.addWidget(self._rg_align_takes())
        lay.addWidget(_vsep())
        lay.addWidget(self._rg_align_ref())
        lay.addStretch()

        return bar

    def _rg_vista(self) -> QWidget:
        w, body = _group_widget("VISUALIZACIÓN")

        # Fila 1: tipo + theta + az
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        r1.addWidget(QLabel("Tipo:"))
        self.combo_tipo = QComboBox(); self.combo_tipo.setFixedWidth(110)
        self.combo_tipo.addItems(["Formas de onda", "RMS por toma"])
        self.combo_tipo.currentIndexChanged.connect(self._on_tipo_changed)
        r1.addWidget(self.combo_tipo)

        self.lbl_theta = QLabel("Theta:")
        r1.addWidget(self.lbl_theta)
        self.combo_theta = QComboBox(); self.combo_theta.setFixedWidth(68)
        r1.addWidget(self.combo_theta)

        self.lbl_az = QLabel("Az:")
        r1.addWidget(self.lbl_az)
        self.combo_az = QComboBox(); self.combo_az.setFixedWidth(68)
        r1.addWidget(self.combo_az)
        body.addLayout(r1)

        # Fila 2: checks + rango Y
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.chk_envelope = QCheckBox("Envolvente"); self.chk_envelope.setChecked(True)
        self.chk_db       = QCheckBox("dB")
        self.chk_db.toggled.connect(self._on_db_toggled)
        r2.addWidget(self.chk_envelope)
        r2.addWidget(self.chk_db)
        r2.addSpacing(8)
        self.chk_yrange = QCheckBox("Fijar Y")
        self.chk_yrange.toggled.connect(self._on_yrange_toggled)
        r2.addWidget(self.chk_yrange)
        r2.addWidget(QLabel("Min:"))
        self.spin_ymin = _le("-60", 50); self.spin_ymin.setEnabled(False)
        r2.addWidget(self.spin_ymin)
        r2.addWidget(QLabel("Max:"))
        self.spin_ymax = _le("0", 50); self.spin_ymax.setEnabled(False)
        r2.addWidget(self.spin_ymax)
        body.addLayout(r2)

        # Fila 3: botón
        r3 = QHBoxLayout()
        btn = QPushButton("Actualizar gráfico"); btn.setObjectName("btn_primary")
        btn.clicked.connect(self._refresh_plot)
        r3.addWidget(btn)
        r3.addStretch()
        body.addLayout(r3)

        return w

    def _rg_hpf(self) -> QWidget:
        w, body = _group_widget("HPF")

        r1 = QHBoxLayout(); r1.setSpacing(4)
        r1.addWidget(QLabel("Corte (Hz):"))
        self.spin_hpf = _le("200", 60)
        r1.addWidget(self.spin_hpf)
        body.addLayout(r1)

        body.addStretch()

        btn = QPushButton("Aplicar HPF")
        btn.clicked.connect(self._on_apply_hpf)
        body.addWidget(btn)

        return w

    def _rg_align_takes(self) -> QWidget:
        w, body = _group_widget("ALINEAR TOMAS")

        r1 = QHBoxLayout(); r1.setSpacing(6)
        r1.addWidget(QLabel("Onset (s):"))
        self.spin_onset = _le("1.0", 50)
        r1.addWidget(self.spin_onset)
        r1.addWidget(QLabel("Umbral (dBFS):"))
        self.spin_thresh = _le("-40", 50)
        r1.addWidget(self.spin_thresh)
        body.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(4)
        r2.addWidget(QLabel("Ref θ:"))
        self.combo_align_theta = QComboBox(); self.combo_align_theta.setFixedWidth(68)
        r2.addWidget(self.combo_align_theta)
        r2.addStretch()
        body.addLayout(r2)

        body.addStretch()

        btn = QPushButton("Alinear tomas")
        btn.clicked.connect(self._on_align_takes)
        body.addWidget(btn)

        return w

    def _rg_align_ref(self) -> QWidget:
        w, body = _group_widget("ALINEAR REF")
        body.addStretch()
        btn = QPushButton("Alinear a\nreferencia")
        btn.clicked.connect(self._on_align_ref)
        body.addWidget(btn)
        body.addStretch()
        return w

    # ── Slots de UI ───────────────────────────────────────────────────────

    def _on_yrange_toggled(self, checked: bool):
        self.spin_ymin.setEnabled(checked)
        self.spin_ymax.setEnabled(checked)

    def _on_db_toggled(self, checked: bool):
        if checked:
            self.chk_envelope.setChecked(True)
            self.chk_envelope.setEnabled(False)
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
        ma = self._ma

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
        theta = self._parse_theta(self.combo_align_theta.currentText())
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
        self._worker = Worker(self._run_align_ref)
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
        for cb in (self.combo_theta, self.combo_az, self.combo_align_theta):
            cb.blockSignals(True)
            cb.clear()

        for th in self._ma.thetas:
            label = "ref" if th == 'ref' else f"{th}°"
            self.combo_theta.addItem(label)
            self.combo_align_theta.addItem(label)

        ref_idx = next((i for i, th in enumerate(self._ma.thetas) if th == 'ref'), 0)
        self.combo_theta.setCurrentIndex(ref_idx)
        self.combo_align_theta.setCurrentIndex(ref_idx)

        self.combo_az.addItem("Todos")
        for az in self._ma.angles:
            self.combo_az.addItem(f"{az}°")

        for cb in (self.combo_theta, self.combo_az, self.combo_align_theta):
            cb.blockSignals(False)

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma = ma
        self._populate_combos()
        self._on_tipo_changed()


# ── Helpers de construcción del Ribbon ────────────────────────────────────────

def _group_widget(title: str) -> tuple[QWidget, QVBoxLayout]:
    """Devuelve (widget, body_layout). El título queda en la parte inferior."""
    outer = QWidget()
    outer.setContentsMargins(0, 0, 0, 0)
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


def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet("color: #2a2d3e;")
    sep.setFixedWidth(1)
    return sep
