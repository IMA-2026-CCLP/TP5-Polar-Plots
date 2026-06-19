"""
ui/tab_calibracion.py — Tab 2: Calibración y conversión a SPL.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QDoubleSpinBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import pyqtSignal

from core.worker import Worker


class TabCalibracion(QWidget):
    """
    Tab de calibración.
    Señales:
        ma_updated(object) — emite el MicArray luego de calibrar/convertir
        log(str)
    """
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma     = None
        self._worker: Worker | None = None
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._make_group_cal())
        lay.addWidget(self._make_group_spl())
        lay.addWidget(self._make_status())
        lay.addStretch()

        scroll.setWidget(container)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _make_group_cal(self) -> QGroupBox:
        g = QGroupBox("ARCHIVOS DE CALIBRACIÓN")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)

        lay.addWidget(QLabel("Carpeta de calibración:"))
        row = QHBoxLayout()
        self.edit_cal_dir = QLineEdit()
        self.edit_cal_dir.setText("C:/Users/abell/OneDrive/Escritorio/TP5-Polar-Plots/data/media")
        btn = QPushButton("Explorar…")
        btn.setFixedWidth(90)
        btn.clicked.connect(self._browse_cal_dir)
        row.addWidget(self.edit_cal_dir)
        row.addWidget(btn)
        lay.addLayout(row)

        lay.addWidget(QLabel("Patrón archivos array (cal):"))
        self.edit_cal_array = QLineEdit()
        self.edit_cal_array.setText("mic_{MIC}_ang_cal.wav")
        lay.addWidget(self.edit_cal_array)

        lay.addWidget(QLabel("Patrón referencia (cal, opcional):"))
        self.edit_cal_ref = QLineEdit()
        self.edit_cal_ref.setText("mic_ref_ang_cal.wav")
        lay.addWidget(self.edit_cal_ref)

        spl_row = QHBoxLayout()
        spl_row.addWidget(QLabel("Nivel del tono de calibración:"))
        self.spin_spl_cal = QDoubleSpinBox()
        self.spin_spl_cal.setRange(80, 120)
        self.spin_spl_cal.setValue(94)
        self.spin_spl_cal.setSuffix(" dB SPL")
        self.spin_spl_cal.setFixedWidth(110)
        spl_row.addWidget(self.spin_spl_cal)
        spl_row.addStretch()
        lay.addLayout(spl_row)

        self.btn_calibrar = QPushButton("Calibrar")
        self.btn_calibrar.setObjectName("btn_primary")
        self.btn_calibrar.setEnabled(False)
        self.btn_calibrar.clicked.connect(self._on_calibrar)
        lay.addWidget(self.btn_calibrar)

        return g

    def _make_group_spl(self) -> QGroupBox:
        g = QGroupBox("CONVERSIÓN A SPL")
        lay = QVBoxLayout(g)

        lbl = QLabel(
            "Convierte el tensor de unidades FS a Pascal (Pa), "
            "usando los factores K calculados en la calibración.\n"
            "Debe ejecutarse antes de compute_directivity()."
        )
        lbl.setObjectName("label_hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        self.btn_to_spl = QPushButton("Convertir a SPL")
        self.btn_to_spl.setObjectName("btn_primary")
        self.btn_to_spl.setEnabled(False)
        self.btn_to_spl.clicked.connect(self._on_to_spl)
        lay.addWidget(self.btn_to_spl)

        return g

    def _make_status(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_status_cal = QLabel("Sin tensor  |  Calibración: —  |  SPL: —")
        self.lbl_status_cal.setObjectName("label_hint")
        lay.addWidget(self.lbl_status_cal)
        lay.addStretch()
        return w

    # ── Slots ─────────────────────────────────────────────────────────────

    def _browse_cal_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Carpeta de calibración")
        if path:
            self.edit_cal_dir.setText(path)

    def _on_calibrar(self):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self.btn_calibrar.setEnabled(False)
        self.log.emit("[Calibración] Iniciando calibración…")
        self._worker = Worker(self._run_calibrar)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_cal_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_calibrar(self):
        import numpy as np
        cal_dir   = self.edit_cal_dir.text().strip()
        cal_array = self.edit_cal_array.text().strip()
        cal_ref   = self.edit_cal_ref.text().strip() or None
        spl_cal   = self.spin_spl_cal.value()
        if not cal_dir or not cal_array:
            raise ValueError("Especificá la carpeta y el patrón de calibración.")

        # Si ya había calibración anterior, la limpiamos para poder repetir
        if self._ma.calibration is not None:
            if self._ma._is_spl:
                # Deshacer la conversión SPL antes de resetear
                P_REF = 20e-6
                scale = (P_REF * 10 ** (self._ma.calibration / 20)).astype(np.float32)
                self._ma.tensor /= scale[np.newaxis, :, np.newaxis]
                self._ma._is_spl = False
                print("  [Re-cal] Conversión SPL deshecha.")
            self._ma.calibration = None
            print("  [Re-cal] Calibración anterior eliminada — recalibrando…")

        self._ma.calibrate(cal_dir, cal_array, cal_ref, spl_cal=spl_cal)
        return self._ma

    def _on_cal_done(self, ma):
        self._ma = ma
        self._refresh_status()
        self.btn_calibrar.setEnabled(True)
        self.btn_to_spl.setEnabled(not ma._is_spl)
        self.log.emit("[Calibración] Calibración completada.")
        self.ma_updated.emit(ma)

    def _on_to_spl(self):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self.btn_to_spl.setEnabled(False)
        self._worker = Worker(self._run_to_spl)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_spl_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_to_spl(self):
        self._ma.to_spl()
        return self._ma

    def _on_spl_done(self, ma):
        self._ma = ma
        self._refresh_status()
        self.btn_to_spl.setEnabled(False)  # ya no se puede aplicar dos veces
        self.log.emit("[Calibración] Tensor convertido a SPL (Pa).")
        self.ma_updated.emit(ma)

    def _on_error(self, msg: str):
        self.btn_calibrar.setEnabled(True)
        self.btn_to_spl.setEnabled(self._ma is not None and self._ma.calibration is not None)
        self.log.emit(f"[ERROR]\n{msg}")

    def _refresh_status(self):
        if self._ma is None:
            self.lbl_status_cal.setText("Sin tensor  |  Calibración: —  |  SPL: —")
            return
        cal_str = "OK" if self._ma.calibration is not None else "Pendiente"
        spl_str = "OK (Pa)" if self._ma._is_spl else "No"
        self.lbl_status_cal.setText(
            f"Tensor: {self._ma.tensor.shape}  |  "
            f"Calibración: {cal_str}  |  SPL: {spl_str}"
        )

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma = ma
        self.btn_calibrar.setEnabled(True)
        self.btn_to_spl.setEnabled(ma.calibration is not None and not ma._is_spl)
        self._refresh_status()
