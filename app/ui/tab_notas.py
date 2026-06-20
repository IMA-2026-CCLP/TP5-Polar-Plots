"""
ui/tab_notas.py — Tab 3: Definición de escala, detección y edición de segmentos.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QFrame, QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from core.worker import Worker

# Escalas predefinidas de ejemplo
SCALE_PRESETS = {
    "La mayor": {
        "La3": 220.00, "Si3": 246.94, "Do#4": 277.18,
        "Re4": 293.66, "Mi4": 329.63, "Fa#4": 369.99,
        "Sol#4": 415.30, "La4": 440.00,
    },
    "Do mayor": {
        "Do4": 261.63, "Re4": 293.66, "Mi4": 329.63,
        "Fa4": 349.23, "Sol4": 392.00, "La4": 440.00,
        "Si4": 493.88,
    },
}


class TabNotas(QWidget):
    """
    Tab de notas.
    Señales:
        ma_updated(object) — MicArray con notas extraídas
        log(str)
    """
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma      = None
        self._segs    = None
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

        lay.addWidget(self._make_group_escala())
        lay.addWidget(self._make_group_params())
        lay.addWidget(self._make_group_segmentos())
        lay.addStretch()

        scroll.setWidget(container)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _make_group_escala(self) -> QGroupBox:
        g = QGroupBox("ESCALA")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        # Presets
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        from PyQt6.QtWidgets import QComboBox
        self.combo_preset = QComboBox()
        self.combo_preset.addItem("— personalizado —")
        for name in SCALE_PRESETS:
            self.combo_preset.addItem(name)
        self.combo_preset.currentTextChanged.connect(self._on_preset)
        preset_row.addWidget(self.combo_preset)
        preset_row.addStretch()
        lay.addLayout(preset_row)

        # Tabla de escala
        self.table_scale = QTableWidget(0, 2)
        self.table_scale.setHorizontalHeaderLabels(["Nota", "Freq (Hz)"])
        self.table_scale.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_scale.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_scale.setFixedHeight(200)
        self.table_scale.setAlternatingRowColors(True)
        lay.addWidget(self.table_scale)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Agregar nota")
        btn_add.clicked.connect(self._add_scale_row)
        btn_del = QPushButton("− Eliminar fila")
        btn_del.setObjectName("btn_danger")
        btn_del.clicked.connect(self._del_scale_row)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        return g

    def _make_group_params(self) -> QGroupBox:
        g = QGroupBox("PARÁMETROS DE DETECCIÓN")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        def spin_row(label, min_, max_, val, suffix=""):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sb = QDoubleSpinBox()
            sb.setRange(min_, max_)
            sb.setValue(val)
            if suffix:
                sb.setSuffix(suffix)
            sb.setFixedWidth(100)
            row.addWidget(sb)
            row.addStretch()
            lay.addLayout(row)
            return sb

        self.spin_tolerance  = spin_row("Tolerancia (cents):", 10, 200, 50, " ¢")
        self.spin_min_purity = spin_row("Pureza mínima:", 0.1, 1.0, 0.8)
        self.spin_min_purity.setSingleStep(0.05)
        self.spin_start_s    = spin_row("Ignorar inicio (s):", 0.0, 10.0, 0.0, " s")
        self.spin_grad_thresh = spin_row("Umbral gradiente F0:", 5, 100, 25, " ¢/f")

        self.btn_detectar = QPushButton("Detectar notas")
        self.btn_detectar.setObjectName("btn_primary")
        self.btn_detectar.setEnabled(False)
        self.btn_detectar.clicked.connect(self._on_detectar)
        lay.addWidget(self.btn_detectar)

        return g

    def _make_group_segmentos(self) -> QGroupBox:
        g = QGroupBox("SEGMENTOS DETECTADOS")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        hint = QLabel(
            "Doble clic en Start/End para editar manualmente (en segundos)."
        )
        hint.setObjectName("label_hint")
        lay.addWidget(hint)

        self.table_segs = QTableWidget(0, 5)
        self.table_segs.setHorizontalHeaderLabels(
            ["Azimuth", "Nota", "Start (s)", "End (s)", "Purity"]
        )
        self.table_segs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_segs.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table_segs.setMinimumHeight(200)
        lay.addWidget(self.table_segs)

        btn_row = QHBoxLayout()
        self.btn_apply_edits = QPushButton("Aplicar ediciones")
        self.btn_apply_edits.setEnabled(False)
        self.btn_apply_edits.clicked.connect(self._on_apply_edits)

        self.btn_extract = QPushButton("Extraer todas las notas")
        self.btn_extract.setObjectName("btn_primary")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._on_extract)

        btn_row.addWidget(self.btn_apply_edits)
        btn_row.addWidget(self.btn_extract)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        return g

    # ── Escala helpers ────────────────────────────────────────────────────

    def _on_preset(self, name: str):
        if name not in SCALE_PRESETS:
            return
        self.table_scale.setRowCount(0)
        for nota, hz in SCALE_PRESETS[name].items():
            self._add_scale_row(nota, hz)

    def _add_scale_row(self, nota: str = "", hz: float = 440.0):
        row = self.table_scale.rowCount()
        self.table_scale.insertRow(row)
        self.table_scale.setItem(row, 0, QTableWidgetItem(nota))
        self.table_scale.setItem(row, 1, QTableWidgetItem(str(hz)))

    def _del_scale_row(self):
        row = self.table_scale.currentRow()
        if row >= 0:
            self.table_scale.removeRow(row)

    def _get_scale(self) -> dict:
        scale = {}
        for i in range(self.table_scale.rowCount()):
            nota_item = self.table_scale.item(i, 0)
            hz_item   = self.table_scale.item(i, 1)
            if nota_item and hz_item:
                try:
                    scale[nota_item.text().strip()] = float(hz_item.text())
                except ValueError:
                    pass
        return scale

    # ── Detección ─────────────────────────────────────────────────────────

    def _on_detectar(self):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        scale = self._get_scale()
        if not scale:
            self.log.emit("[Notas] La escala está vacía.")
            return
        self.btn_detectar.setEnabled(False)
        self._worker = Worker(self._run_detect, scale)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_detect_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_detect(self, scale):
        self._ma.scale = scale
        segs = self._ma.detect_notes(
            scale           = scale,
            tolerance_cents = self.spin_tolerance.value(),
            min_purity      = self.spin_min_purity.value(),
            start_s         = self.spin_start_s.value(),
            gradient_thresh = self.spin_grad_thresh.value(),
        )
        return segs

    def _on_detect_done(self, segs):
        self._segs = segs
        self._populate_segs_table(segs)
        self.btn_detectar.setEnabled(True)
        self.btn_apply_edits.setEnabled(True)
        self.btn_extract.setEnabled(True)
        self.log.emit("[Notas] Detección completada.")

    # ── Tabla de segmentos ────────────────────────────────────────────────

    def _populate_segs_table(self, segs):
        self.table_segs.setRowCount(0)
        if self._ma is None or not segs:
            return
        for i_az, (az, seg_dict) in enumerate(zip(self._ma.angles, segs)):
            for nota, info in seg_dict.items():
                row = self.table_segs.rowCount()
                self.table_segs.insertRow(row)

                az_item    = QTableWidgetItem(f"{az}°")
                nota_item  = QTableWidgetItem(nota)
                start_item = QTableWidgetItem(f"{info['start'] / self._ma.sr:.3f}")
                end_item   = QTableWidgetItem(f"{info['end'] / self._ma.sr:.3f}")
                pur_item   = QTableWidgetItem(f"{info['purity']:.2f}")

                az_item.setFlags(az_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                nota_item.setFlags(nota_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                pur_item.setFlags(pur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # Color por purity
                pur = info['purity']
                if pur >= 0.9:
                    color = QColor("#1a3a1a")
                elif pur >= 0.8:
                    color = QColor("#3a3010")
                else:
                    color = QColor("#3a1010")
                for item in (az_item, nota_item, start_item, end_item, pur_item):
                    item.setBackground(color)

                self.table_segs.setItem(row, 0, az_item)
                self.table_segs.setItem(row, 1, nota_item)
                self.table_segs.setItem(row, 2, start_item)
                self.table_segs.setItem(row, 3, end_item)
                self.table_segs.setItem(row, 4, pur_item)

    def _on_apply_edits(self):
        """Lee la tabla editada y aplica los cambios a self._segs."""
        if self._ma is None or self._segs is None:
            return
        for row in range(self.table_segs.rowCount()):
            try:
                az_str   = self.table_segs.item(row, 0).text().replace("°", "")
                nota     = self.table_segs.item(row, 1).text()
                start_s  = float(self.table_segs.item(row, 2).text())
                end_s    = float(self.table_segs.item(row, 3).text())
                azimuth  = int(az_str)
                self._ma.edit_segment(self._segs, azimuth, nota, start_s, end_s)
            except Exception as e:
                self.log.emit(f"[Notas] Error en fila {row}: {e}")
        self._populate_segs_table(self._segs)
        self.log.emit("[Notas] Ediciones aplicadas.")

    # ── Extracción ────────────────────────────────────────────────────────

    def _on_extract(self):
        if self._ma is None or self._segs is None or (self._worker and self._worker.isRunning()):
            return
        self.btn_extract.setEnabled(False)
        self._worker = Worker(self._run_extract)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_extract_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_extract(self):
        self._ma.extract_all_notes(self._segs)
        return self._ma

    def _on_extract_done(self, ma):
        self._ma = ma
        self.btn_extract.setEnabled(True)
        self.log.emit(f"[Notas] Notas extraídas: {list(ma.notes.keys())}")
        self.ma_updated.emit(ma)

    def _on_error(self, msg: str):
        self.btn_detectar.setEnabled(True)
        self.btn_extract.setEnabled(self._segs is not None)
        self.log.emit(f"[ERROR]\n{msg}")

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma   = ma
        self._segs = None
        self.btn_detectar.setEnabled(True)
        self.btn_extract.setEnabled(False)
        self.btn_apply_edits.setEnabled(False)
        self.table_segs.setRowCount(0)

    def detect_notes(self, dur: float, margin: float, thresh: float, ref_theta):
        """Llamado desde el ribbon — desencadena detección con los parámetros del tab."""
        self._on_detectar()
