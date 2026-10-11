"""
ui/tab_notas.py — Tab 3: Detección y edición de segmentos de notas.
"""
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
    QDialog, QTabWidget, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QColor

from core.worker import Worker
from ui.f0_editor import F0EditorWidget
from ui.waveform_editor import WaveformEditorWidget

from ui.scale_dialog import ScaleEditorDialog   # noqa: F401  (MainWindow lo importa desde acá)
from core import scales as _scales


class TabNotas(QWidget):
    """
    Tab de notas.
    Señales:
        ma_updated(object) — MicArray con notas extraídas
        log(str)
    """
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)
    onset_dragged = pyqtSignal(int, float)   # onset marcado a mano en la señal dB (az_idx, segundos)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma      = None
        self._segs    = None
        self._worker: Worker | None = None
        self._current_scale: dict = _scales.default_scale()
        self._tolerance_cents: float = 50.0
        self._min_purity: float      = 0.8
        self._start_s: float         = 0.0
        self._gradient_thresh: float = 25.0
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Cada paso (solapa de arriba) tiene su tira de controles, armada por NativeRibbon y embebida
        # en set_notas_controls(), y debajo su gráfico.
        self._slots = [QVBoxLayout() for _ in range(3)]
        for sl in self._slots:
            sl.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self.btn_apply_edits = QPushButton("Aplicar ediciones")
        self.btn_apply_edits.setEnabled(False)
        self.btn_apply_edits.clicked.connect(self._on_apply_edits)

        # Verde formal: distingue el paso que hay que apretar para que las notas detectadas
        # pasen a existir como MicArray (ma.notes) — sin esto, "A procesar" no tiene nada.
        self.btn_extract = QPushButton("Extraer notas")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._on_extract)
        self.btn_extract.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; font-weight:bold; }"
            "QPushButton:hover:!disabled { background:#36913a; }"
            "QPushButton:disabled { background:#9e9e9e; color:#e0e0e0; }"
        )

        btn_row.addWidget(self.btn_apply_edits)
        btn_row.addWidget(self.btn_extract)
        btn_row.addStretch(1)

        # Dos vistas en pestañas. Por defecto la señal en dB del micrófono de referencia con todas las tomas
        # (ahí se alinea y se marca el onset a mano); la otra es el editor F0 con la tabla de segmentos.
        self.sig_editor = WaveformEditorWidget()
        self.sig_editor.log.connect(self.log)
        self.sig_editor.onset_dragged.connect(self.onset_dragged)
        self._sig_view = (None, 20.0)          # (yrange, suavizado ms) que fija la ventana principal

        self.f0_editor = F0EditorWidget()
        self.f0_editor.log.connect(self.log)
        self.f0_editor.segments_changed.connect(self._on_f0_segments_changed)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        body.addWidget(self.f0_editor, 1)
        body.addWidget(self._build_table_panel())

        # Un solo giro: el micrófono de referencia contra el resto de los micrófonos del array.
        self.mics_editor = WaveformEditorWidget()
        self.mics_editor.log.connect(self.log)
        self._mics_az = QComboBox()
        self._mics_az.setToolTip("Giro (azimut) de la toma a mostrar")
        self._mics_az.currentIndexChanged.connect(lambda _=None: self._render_mics())
        mv = QVBoxLayout()
        mv.setContentsMargins(0, 0, 0, 0)
        mrow = QHBoxLayout()
        mlabel = QLabel("Giro:")
        mlabel.setStyleSheet("font-weight: bold;")
        mrow.addWidget(mlabel)
        mrow.addWidget(self._mics_az)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        mv.addWidget(self.mics_editor, 1)

        def page(slot, content_layout=None, content_widget=None, extra_row=None):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 6, 0, 0)
            v.setSpacing(6)
            v.addLayout(slot)
            if extra_row is not None:
                v.addLayout(extra_row)
            if content_widget is not None:
                v.addWidget(content_widget, 1)
            else:
                v.addLayout(content_layout, 1)
            return w

        self.tabs = QTabWidget()
        self.tabs.addTab(page(self._slots[0], content_widget=self.sig_editor), "1 - Alineación entre tomas")
        self.tabs.addTab(page(self._slots[1], content_layout=mv), "2 - TDOA")
        self.tabs.addTab(page(self._slots[2], content_layout=body, extra_row=btn_row), "3 - Segmentación")
        root.addWidget(self.tabs, 1)

    def set_notas_controls(self, strips):
        """Recibe las tres tiras de NativeRibbon.build_notas_panel() (tomas, TDOA, escala+detección),
        una por solapa, arriba de cada gráfico."""
        for slot, w in zip(self._slots, strips):
            w.setFixedHeight(w.sizeHint().height())     # alto justo: el resto es para el gráfico
            slot.addWidget(w)

    def _build_table_panel(self) -> QWidget:
        """Tabla de segmentos detectados, siempre visible al costado del gráfico temporal."""
        panel = QWidget()
        panel.setFixedWidth(360)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)

        hint = QLabel(
            "Doble clic en Start/End para editar. "
            "Arrastrá los cursores en el plot F0 para ajuste visual."
        )
        hint.setObjectName("label_hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.table_segs = QTableWidget(0, 5)
        self.table_segs.setHorizontalHeaderLabels(
            ["Azimuth", "Nota", "Start (s)", "End (s)", "Purity"]
        )
        self.table_segs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_segs.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        lay.addWidget(self.table_segs)
        return panel

    # ── Escala API ────────────────────────────────────────────────────────

    def get_scale(self) -> dict:
        return dict(self._current_scale)

    def set_scale(self, scale: dict):
        self._current_scale = dict(scale)
        if self._ma is not None:
            self._ma.scale = self._current_scale

    def _set_scale_from_preset(self, name: str):
        _, sc = _scales.find(name)
        if sc:
            self._current_scale = sc
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
        self._worker.label = "Detectando notas…"
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
        self._worker.label = "Extrayendo notas…"
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
        self.sig_editor.set_ma(ma)
        self.mics_editor.set_ma(ma)
        keep = self._mics_az.currentData()
        self._mics_az.blockSignals(True)
        self._mics_az.clear()
        for a in ma.angles:
            self._mics_az.addItem(f"{a}°", a)
        i = self._mics_az.findData(keep) if keep is not None else -1
        self._mics_az.setCurrentIndex(i if i >= 0 else 0)
        self._mics_az.blockSignals(False)
        self._render_signal()
        self._render_mics()

    def set_signal_view(self, yrange, smoothing_ms):
        """Rango Y y suavizado de la señal dB (los mismos que usa Procesamiento)."""
        self._sig_view = (yrange, float(smoothing_ms))
        self._render_signal()
        self._render_mics()

    def _render_signal(self):
        if self._ma is None:
            return
        yrange, smooth = self._sig_view
        # micrófono de referencia, todas las tomas superpuestas, en dB (envolvente)
        self.sig_editor.render('ref', None, True, True, yrange, smooth)

    def _render_mics(self):
        az = self._mics_az.currentData()
        if self._ma is None or az is None:
            return
        yrange, smooth = self._sig_view
        # theta=None + azimut fijo → todos los micrófonos de esa toma superpuestos (con leyenda por mic)
        self.mics_editor.render(None, az, True, True, yrange, smooth)

    def set_align_params(self, onset, thresh, theta):
        self.sig_editor.set_align_params(onset, thresh, theta)

    def show_f0(self):
        self.tabs.setCurrentIndex(2)           # solapa 3 - Segmentación (editor F0 + tabla)

    def detect_notes(self, tol: float, purity: float, start_s: float,
                     grad: float, ref_theta):
        self._tolerance_cents = tol
        self._min_purity      = purity
        self._start_s         = start_s
        self._gradient_thresh = grad
        self._on_detectar()

    def apply_theme(self, palette: dict):
        self.f0_editor.apply_theme(palette)
        self.sig_editor.apply_theme(palette)
        self.mics_editor.apply_theme(palette)
