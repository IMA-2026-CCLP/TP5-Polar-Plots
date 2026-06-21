"""
ui/tab_notas.py — Tab 3: Detección y edición de segmentos de notas.
"""
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSplitter,
    QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QColor

from core.worker import Worker
from ui.f0_editor import F0EditorWidget

# Escalas predefinidas
SCALE_PRESETS = {
    "Fa mayor": {
        "Fa4": 349.23, "Sol4": 392.00, "La4": 440.00,
        "Sib4": 466.16, "Do5": 523.25, "Re5": 587.33,
        "Mi5": 659.25, "Fa5": 698.46,
    },
}


class ScaleEditorDialog(QDialog):
    """Popup para ver y editar la escala activa (notas y frecuencias)."""

    def __init__(self, scale: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar escala")
        self.setMinimumSize(320, 300)
        self.resize(360, 340)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Nota", "Freq (Hz)"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        lay.addWidget(self._table)

        for nota, hz in scale.items():
            self._add_row(nota, hz)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Agregar nota")
        btn_add.clicked.connect(lambda: self._add_row())
        btn_del = QPushButton("− Eliminar fila")
        btn_del.clicked.connect(self._del_row)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _add_row(self, nota: str = "", hz: float = 440.0):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(str(nota)))
        self._table.setItem(row, 1, QTableWidgetItem(str(hz)))

    def _del_row(self):
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def get_scale(self) -> dict:
        scale = {}
        for i in range(self._table.rowCount()):
            n = self._table.item(i, 0)
            f = self._table.item(i, 1)
            if n and f:
                try:
                    scale[n.text().strip()] = float(f.text())
                except ValueError:
                    pass
        return scale


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
        self._current_scale: dict = dict(list(SCALE_PRESETS.values())[0])
        self._tolerance_cents: float = 50.0
        self._min_purity: float      = 0.8
        self._start_s: float         = 0.0
        self._gradient_thresh: float = 25.0
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(6)

        # Mitad superior — tabla de segmentos
        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(12, 8, 12, 4)
        top_lay.setSpacing(4)
        top_lay.addWidget(self._make_group_segmentos())
        splitter.addWidget(top)

        # Mitad inferior — editor F0 interactivo
        self.f0_editor = F0EditorWidget()
        self.f0_editor.log.connect(self.log)
        self.f0_editor.segments_changed.connect(self._on_f0_segments_changed)
        splitter.addWidget(self.f0_editor)

        splitter.setSizes([260, 400])
        root.addWidget(splitter)

    def _make_group_segmentos(self) -> QGroupBox:
        g = QGroupBox("SEGMENTOS DETECTADOS")
        lay = QVBoxLayout(g)
        lay.setSpacing(6)

        hint = QLabel(
            "Doble clic en Start/End para editar. "
            "Arrastrá los cursores en el plot F0 para ajuste visual."
        )
        hint.setObjectName("label_hint")
        lay.addWidget(hint)

        self.table_segs = QTableWidget(0, 5)
        self.table_segs.setHorizontalHeaderLabels(
            ["Azimuth", "Nota", "Start (s)", "End (s)", "Purity"]
        )
        self.table_segs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_segs.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table_segs.setMinimumHeight(120)
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

    # ── Escala API ────────────────────────────────────────────────────────

    def get_scale(self) -> dict:
        return dict(self._current_scale)

    def set_scale(self, scale: dict):
        self._current_scale = dict(scale)
        if self._ma is not None:
            self._ma.scale = self._current_scale

    def _set_scale_from_preset(self, name: str):
        if name in SCALE_PRESETS:
            self._current_scale = dict(SCALE_PRESETS[name])
            if self._ma is not None:
                self._ma.scale = self._current_scale

    # ── Detección ─────────────────────────────────────────────────────────

    def _on_detectar(self):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        if not self._current_scale:
            self.log.emit("[Notas] La escala está vacía.")
            return
        self._ma.scale = self._current_scale
        self._worker = Worker(self._run_detect, self._current_scale)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_detect_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_detect(self, scale):
        self._ma.scale = scale
        segs = self._ma.detect_notes(
            scale           = scale,
            tolerance_cents = self._tolerance_cents,
            min_purity      = self._min_purity,
            start_s         = self._start_s,
            gradient_thresh = self._gradient_thresh,
        )
        return segs

    def _on_detect_done(self, segs):
        self._segs = segs
        self._populate_segs_table(segs)
        self.f0_editor.set_segments(segs)
        self.btn_apply_edits.setEnabled(True)
        self.btn_extract.setEnabled(True)
        self.log.emit("[Notas] Detección completada.")

    # ── Tabla de segmentos ────────────────────────────────────────────────

    def _populate_segs_table(self, segs):
        self.table_segs.setRowCount(0)
        if self._ma is None or not segs:
            return
        for az, seg_dict in zip(self._ma.angles, segs):
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

    def _on_f0_segments_changed(self, az_idx: int):
        """Callback cuando el usuario arrastra un cursor en el F0 editor."""
        if self._segs is not None:
            self._populate_segs_table(self._segs)

    def _on_apply_edits(self):
        if self._ma is None or self._segs is None:
            return

        # Deshabilitar edición fuerza a Qt a cerrar y destruir el widget editor
        # de celda activo antes de cualquier manipulación de la tabla.
        # Es más confiable que setCurrentIndex(QModelIndex()).
        self.table_segs.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        # Leer todos los valores ANTES de tocar la tabla
        rows_data = []
        for row in range(self.table_segs.rowCount()):
            try:
                i0 = self.table_segs.item(row, 0)
                i1 = self.table_segs.item(row, 1)
                i2 = self.table_segs.item(row, 2)
                i3 = self.table_segs.item(row, 3)
                if None in (i0, i1, i2, i3):
                    continue
                rows_data.append((
                    int(i0.text().replace("°", "")),
                    i1.text(),
                    float(i2.text()),
                    float(i3.text()),
                ))
            except Exception as e:
                self.log.emit(f"[Notas] Error leyendo fila {row}: {e}")

        # Aplicar ediciones al modelo
        for azimuth, nota, start_s, end_s in rows_data:
            try:
                self._ma.edit_segment(self._segs, azimuth, nota, start_s, end_s)
            except Exception as e:
                self.log.emit(f"[Notas] Error editando {nota}@{azimuth}°: {e}")

        # Repoblar tabla y restaurar edición
        try:
            self._populate_segs_table(self._segs)
            self.f0_editor.set_segments(self._segs)
            self.log.emit("[Notas] Ediciones aplicadas.")
        except Exception as e:
            self.log.emit(f"[Notas] Error al actualizar vista: {e}")
        finally:
            self.table_segs.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked
            )

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
        self.btn_extract.setEnabled(self._segs is not None)
        self.log.emit(f"[ERROR]\n{msg}")

    # ── Máscara save / load ───────────────────────────────────────────────

    def save_mask(self, path: str):
        """Guarda segments a JSON serializable."""
        if self._segs is None or self._ma is None:
            self.log.emit("[Notas] Sin segmentos para guardar.")
            return
        data = {
            "sr"      : int(self._ma.sr),
            "angles"  : [int(a) for a in self._ma.angles],
            "segments": [
                {
                    note: {
                        "start" : int(info["start"]),
                        "end"   : int(info["end"]),
                        "purity": float(info["purity"]),
                    }
                    for note, info in segs.items()
                }
                for segs in self._segs
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.log.emit(f"[Notas] Máscara guardada → {path}")

    def load_mask(self, path: str):
        """Carga segments desde JSON y actualiza tabla + editor F0."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # validación básica
        if self._ma is not None:
            if data.get("sr") != self._ma.sr:
                self.log.emit("[WARN] sr de la máscara no coincide con el MicArray actual.")
            if data.get("angles") != [int(a) for a in self._ma.angles]:
                self.log.emit("[WARN] ángulos de la máscara no coinciden con el MicArray actual.")

        self._segs = [
            {
                note: {
                    "start" : int(info["start"]),
                    "end"   : int(info["end"]),
                    "purity": float(info["purity"]),
                }
                for note, info in segs.items()
            }
            for segs in data["segments"]
        ]
        self._populate_segs_table(self._segs)
        self.f0_editor.set_segments(self._segs)
        self.btn_apply_edits.setEnabled(True)
        self.btn_extract.setEnabled(True)
        self.log.emit(f"[Notas] Máscara cargada ← {path}")

    # ── API pública ───────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma   = ma
        self._segs = None
        self.btn_extract.setEnabled(False)
        self.btn_apply_edits.setEnabled(False)
        self.table_segs.setRowCount(0)
        ma.scale = self._current_scale
        self.f0_editor.set_ma(ma)

    def detect_notes(self, tol: float, purity: float, start_s: float,
                     grad: float, ref_theta):
        self._tolerance_cents = tol
        self._min_purity      = purity
        self._start_s         = start_s
        self._gradient_thresh = grad
        self._on_detectar()

    def apply_theme(self, palette: dict):
        self.f0_editor.apply_theme(palette)
