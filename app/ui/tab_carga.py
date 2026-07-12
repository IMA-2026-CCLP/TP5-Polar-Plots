"""
ui/tab_carga.py — Tab 1: Carga de audios / tensor NPZ y preprocesamiento.
"""
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QStackedWidget, QScrollArea, QFrame,
)
from PyQt6.QtCore import pyqtSignal

from core.worker import Worker


class TabCarga(QWidget):
    """
    Tab de carga.
    Señales:
        ma_ready(object)  — emite el MicArray listo para usar
        log(str)          — línea de log para el dock principal
    """
    ma_ready = pyqtSignal(object)
    log      = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Worker | None = None
        self._ma = None
        self._current_mode = 'audio'
        self._loaded_ui_state: dict = {}
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

        lay.addWidget(self._make_group_fuente())
        lay.addWidget(self._make_group_acciones())
        lay.addWidget(self._make_status_bar())
        lay.addStretch()

        scroll.setWidget(container)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _make_group_fuente(self) -> QGroupBox:
        g = QGroupBox("FUENTE")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)
        lay.setContentsMargins(12, 16, 12, 12)

        self._source_stack = QStackedWidget()
        self._source_stack.addWidget(self._make_panel_audio())
        self._source_stack.addWidget(self._make_panel_npz())
        lay.addWidget(self._source_stack)

        return g

    def _make_panel_audio(self) -> QWidget:
        panel = QWidget()
        lay   = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Carpeta de audios:"))
        row = QHBoxLayout()
        self.edit_carpeta = QLineEdit()
        self.edit_carpeta.setText("C:/Users/abell/OneDrive/Escritorio/TP5-Polar-Plots/data/media")
        btn = QPushButton("Explorar…")
        btn.setFixedWidth(90)
        btn.clicked.connect(self._browse_carpeta)
        row.addWidget(self.edit_carpeta)
        row.addWidget(btn)
        lay.addLayout(row)

        lay.addWidget(QLabel("Patrón archivos array:"))
        self.edit_array_pattern = QLineEdit()
        self.edit_array_pattern.setText("mic_{MIC}_ang_forte_{H}.wav")
        lay.addWidget(self.edit_array_pattern)

        lay.addWidget(QLabel("Patrón referencia (opcional):"))
        self.edit_ref_pattern = QLineEdit()
        self.edit_ref_pattern.setText("mic_ref_ang_forte_{H}.wav")
        lay.addWidget(self.edit_ref_pattern)

        return panel

    def _make_panel_npz(self) -> QWidget:
        panel = QWidget()
        lay   = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Archivo de sesión (.cclp / .npz):"))
        row = QHBoxLayout()
        self.edit_npz_path = QLineEdit()
        self.edit_npz_path.setPlaceholderText("sesion.cclp")
        btn = QPushButton("Explorar…")
        btn.setFixedWidth(90)
        btn.clicked.connect(self._browse_npz)
        row.addWidget(self.edit_npz_path)
        row.addWidget(btn)
        lay.addLayout(row)

        return panel

    def _make_group_preprocesamiento(self) -> QGroupBox:
        g = QGroupBox("PREPROCESAMIENTO (solo para audios crudos)")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)

        # HPF
        hpf_row = QHBoxLayout()
        self.chk_hpf = QCheckBox("High-pass filter (Hz):")
        self.spin_hpf = QDoubleSpinBox()
        self.spin_hpf.setRange(20, 1000)
        self.spin_hpf.setValue(200)
        self.spin_hpf.setSuffix(" Hz")
        self.spin_hpf.setFixedWidth(100)
        self.spin_hpf.setEnabled(False)
        self.chk_hpf.toggled.connect(self.spin_hpf.setEnabled)
        hpf_row.addWidget(self.chk_hpf)
        hpf_row.addWidget(self.spin_hpf)
        hpf_row.addStretch()
        lay.addLayout(hpf_row)

        # Align takes
        at_row = QHBoxLayout()
        self.chk_align_takes = QCheckBox("Alinear tomas — onset target:")
        self.spin_onset = QDoubleSpinBox()
        self.spin_onset.setRange(0.1, 5.0)
        self.spin_onset.setValue(1.0)
        self.spin_onset.setSuffix(" s")
        self.spin_onset.setFixedWidth(80)
        self.spin_onset.setEnabled(False)
        lbl_thresh = QLabel("  umbral:")
        self.spin_thresh_at = QDoubleSpinBox()
        self.spin_thresh_at.setRange(-80, 0)
        self.spin_thresh_at.setValue(-40)
        self.spin_thresh_at.setSuffix(" dBFS")
        self.spin_thresh_at.setFixedWidth(90)
        self.spin_thresh_at.setEnabled(False)
        self.chk_align_takes.toggled.connect(self.spin_onset.setEnabled)
        self.chk_align_takes.toggled.connect(self.spin_thresh_at.setEnabled)
        at_row.addWidget(self.chk_align_takes)
        at_row.addWidget(self.spin_onset)
        at_row.addWidget(lbl_thresh)
        at_row.addWidget(self.spin_thresh_at)
        at_row.addStretch()
        lay.addLayout(at_row)

        # Align to ref
        self.chk_align_ref = QCheckBox("Alinear thetas a referencia (GCC-PHAT)")
        lay.addWidget(self.chk_align_ref)

        return g

    def _make_group_acciones(self) -> QGroupBox:
        g = QGroupBox("ACCIONES")
        lay = QVBoxLayout(g)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_cargar = QPushButton("Cargar y procesar")
        self.btn_cargar.setObjectName("btn_primary")
        self.btn_cargar.clicked.connect(self._on_cargar)
        btn_row.addWidget(self.btn_cargar)

        self.btn_guardar_npz = QPushButton("Guardar tensor .npz")
        self.btn_guardar_npz.setEnabled(False)
        self.btn_guardar_npz.clicked.connect(self._on_guardar_npz)
        btn_row.addWidget(self.btn_guardar_npz)

        btn_row.addStretch()
        lay.addLayout(btn_row)
        return g

    def _make_status_bar(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 4, 0, 0)
        self.lbl_status = QLabel("Sin tensor cargado.")
        self.lbl_status.setStyleSheet(
            "color: #8a96be; font-size: 10pt;"
        )
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        lay.addStretch()
        return w

    # ── Slots ─────────────────────────────────────────────────────────────

    def _browse_carpeta(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de audios")
        if path:
            self.edit_carpeta.setText(path)

    def _browse_npz(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar sesión", "",
            "Sesión CCLP (*.cclp);;NPZ tensor (*.npz)"
        )
        if path:
            self.edit_npz_path.setText(path)

    def _on_cargar(self):
        if self._worker and self._worker.isRunning():
            return

        self.btn_cargar.setEnabled(False)
        self.lbl_status.setText("Cargando…")

        if self._current_mode == 'audio':
            self._worker = Worker(self._load_from_audio)
        else:
            self._worker = Worker(self._load_from_npz)

        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_load_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _load_from_audio(self):
        from mic_array.patron import MicArray

        carpeta       = self.edit_carpeta.text().strip()
        array_pattern = self.edit_array_pattern.text().strip()
        ref_pattern   = self.edit_ref_pattern.text().strip() or None

        if not carpeta or not array_pattern:
            raise ValueError("Especificá la carpeta y el patrón de archivos.")

        return MicArray.from_audio(carpeta, array_pattern, ref_pattern)

    def _load_from_npz(self):
        from mic_array.patron import MicArray
        from core.session import load_cclp

        path = self.edit_npz_path.text().strip()
        if not path:
            raise ValueError("Especificá la ruta del archivo.")
        if path.endswith('.cclp'):
            ma, ui_state = load_cclp(path)
            self._loaded_ui_state = ui_state
            return ma
        self._loaded_ui_state = {}
        return MicArray.from_tensor(path)

    def _on_load_done(self, ma):
        self._ma = ma
        shape    = ma.tensor.shape
        self.lbl_status.setText(
            f"Tensor cargado — forma: {shape}  |  sr: {ma.sr} Hz  |  "
            f"azimuths: {ma.angles}  |  thetas: {ma.n_thetas}"
        )
        self.btn_guardar_npz.setEnabled(True)
        self.btn_cargar.setEnabled(True)
        self.log.emit(f"[Carga] Tensor listo — {shape}")
        self.ma_ready.emit(ma)

    def _on_guardar_npz(self, ui_state: dict | None = None):
        if self._ma is None:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Guardar sesión", "",
            "Sesión CCLP (*.cclp);;NPZ tensor (*.npz)"
        )
        if not path:
            return

        # El diálogo nativo no siempre agrega la extensión del filtro elegido
        # (depende del sistema operativo) → si el usuario no la tipeó, se
        # infiere del filtro seleccionado, con .cclp como default.
        if not path.lower().endswith(('.cclp', '.npz')):
            path += '.npz' if 'npz' in selected_filter.lower() else '.cclp'

        if path.lower().endswith('.cclp'):
            from core.session import save_cclp
            save_cclp(path, self._ma, ui_state or {})
        else:
            self._ma.save(path)
        self.log.emit(f"[Carga] Sesión guardada → {path}")

    def _on_error(self, msg: str):
        self.btn_cargar.setEnabled(True)
        self.lbl_status.setText("Error al cargar.")
        self.log.emit(f"[ERROR]\n{msg}")

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        """Permite que MainWindow inyecte un MicArray (ej.: cargado por menú)."""
        self._on_load_done(ma)

    def set_source_mode(self, mode: str):
        """Cambia el panel visible (audio / tensor) sin disparar carga."""
        self._current_mode = mode
        self._source_stack.setCurrentIndex(0 if mode == 'audio' else 1)
