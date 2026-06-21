"""
ui/f0_editor.py — Editor interactivo de segmentos F0 con cursores arrastrables.
Requiere: pyqtgraph
"""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

from core.worker import Worker

# Paleta de colores (R,G,B) — una por nota
_PALETTE = [
    (80,  140, 255),
    (255,  80,  80),
    (70,  200, 100),
    (255, 180,  50),
    (180, 100, 255),
    (50,  210, 210),
    (255, 220,  50),
    (255, 100, 220),
]

HOP_LENGTH = 512   # debe coincidir con detect_notes
BAND_CENTS = 50    # semiancho de banda coloreada (¢)


class F0EditorWidget(QWidget):
    """
    Plot interactivo de F0 tracking con InfiniteLines arrastrables por nota.

    Señales:
        segments_changed(int)  — az_idx cuyo segmento fue editado
        log(str)
    """
    segments_changed = pyqtSignal(int)
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma: object         = None
        self._segments: list     = None
        self._az_idx: int        = 0
        self._theta              = 'ref'
        self._worker: Worker     = None
        self._note_lines: dict   = {}   # note -> {'start': InfiniteLine, 'end': InfiniteLine}
        self._f0_data: dict      = None
        self._build_ui()

    # ── construcción ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # barra de controles
        ctrl = QHBoxLayout(); ctrl.setSpacing(6)
        ctrl.addWidget(QLabel("Azimuth:"))
        self.combo_az = QComboBox()
        self.combo_az.setFixedWidth(76)
        self.combo_az.wheelEvent = lambda e: e.ignore()
        ctrl.addWidget(self.combo_az)
        ctrl.addSpacing(8)
        ctrl.addWidget(QLabel("Mic ref:"))
        self.combo_theta = QComboBox()
        self.combo_theta.setFixedWidth(76)
        self.combo_theta.wheelEvent = lambda e: e.ignore()
        ctrl.addWidget(self.combo_theta)
        ctrl.addSpacing(10)
        self.btn_compute = QPushButton("Calcular F0")
        self.btn_compute.setEnabled(False)
        ctrl.addWidget(self.btn_compute)
        self._lbl_status = QLabel("")
        ctrl.addWidget(self._lbl_status)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # plot pyqtgraph
        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel('bottom', 'Tiempo (s)')
        self._plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._plot, 1)

        self._apply_pg_theme()

        # conexiones
        self.combo_az.currentIndexChanged.connect(self._on_az_changed)
        self.combo_theta.currentIndexChanged.connect(self._on_theta_changed)
        self.btn_compute.clicked.connect(self._compute_f0)

    def _apply_pg_theme(self):
        from ui import theme as _t
        p = _t.current()
        self._plot.setBackground(p['plot_bg'])
        self._plot.getAxis('bottom').setPen(pg.mkPen(p['text2']))
        self._plot.getAxis('left').setPen(pg.mkPen(p['text2']))
        self._plot.getAxis('bottom').setTextPen(pg.mkPen(p['text2']))
        self._plot.getAxis('left').setTextPen(pg.mkPen(p['text2']))

    def apply_theme(self, palette: dict):
        self._plot.setBackground(palette['plot_bg'])
        self._plot.getAxis('bottom').setPen(pg.mkPen(palette['text2']))
        self._plot.getAxis('left').setPen(pg.mkPen(palette['text2']))
        self._plot.getAxis('bottom').setTextPen(pg.mkPen(palette['text2']))
        self._plot.getAxis('left').setTextPen(pg.mkPen(palette['text2']))

    # ── API pública ──────────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma       = ma
        self._f0_data  = None
        self._note_lines = {}
        self._plot.clear()
        self._lbl_status.setText("")

        # poblar combo azimuth
        self.combo_az.blockSignals(True)
        self.combo_az.clear()
        for az in ma.angles:
            self.combo_az.addItem(f"{az}°")
        self.combo_az.blockSignals(False)

        # poblar combo theta
        self.combo_theta.blockSignals(True)
        self.combo_theta.clear()
        for th in ma.thetas:
            self.combo_theta.addItem("ref" if th == "ref" else f"{th}°")
        ref_idx = next((i for i, t in enumerate(ma.thetas) if t == "ref"), 0)
        self.combo_theta.setCurrentIndex(ref_idx)
        self._theta = 'ref'
        self.combo_theta.blockSignals(False)

        self.btn_compute.setEnabled(True)

    def set_segments(self, segments):
        """Carga segmentos y redibuja cursores si ya hay F0."""
        self._segments = segments
        if self._f0_data is not None:
            self._redraw_cursors()

    # ── slots internos ────────────────────────────────────────────────────────

    def _on_az_changed(self):
        self._az_idx = self.combo_az.currentIndex()
        if self._f0_data is not None:
            self._compute_f0()

    def _on_theta_changed(self):
        text = self.combo_theta.currentText()
        self._theta = 'ref' if text == 'ref' else int(text.rstrip('°'))
        if self._f0_data is not None:
            self._compute_f0()

    # ── cómputo F0 ────────────────────────────────────────────────────────────

    def _compute_f0(self):
        if self._ma is None or (self._worker and self._worker.isRunning()):
            return
        self._plot.clear()
        self._note_lines = {}
        self._f0_data    = None
        self.btn_compute.setEnabled(False)
        az = self._ma.angles[self._az_idx]
        self._lbl_status.setText(f"Calculando {az}°…")

        self._worker = Worker(self._run_f0, self._az_idx, self._theta)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_f0_done)
        self._worker.error.connect(self._on_f0_error)
        self._worker.start()

    def _run_f0(self, az_idx, theta):
        import librosa
        ma    = self._ma
        scale = ma.scale
        if scale is None:
            raise RuntimeError("Definí la escala antes de calcular F0.")

        i_th       = ma._th_to_col(theta)
        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()), dtype=float)
        fmin       = float(note_freqs.min() * 0.9)
        fmax       = float(note_freqs.max() * 1.1)
        f_ref      = float(note_freqs[0])

        signal = ma.tensor[az_idx, i_th, :].astype(np.float32)
        f0, voiced, _ = librosa.pyin(
            signal, fmin=fmin, fmax=fmax,
            sr=ma.sr, hop_length=HOP_LENGTH, fill_na=np.nan,
        )

        t        = np.arange(len(f0)) * HOP_LENGTH / ma.sr
        f0_cents = np.where(voiced,
                            1200.0 * np.log2(np.where(voiced, f0, f_ref) / f_ref),
                            np.nan)
        note_cents = {n: float(1200.0 * np.log2(f / f_ref))
                      for n, f in scale.items()}

        return dict(
            t=t, f0_cents=f0_cents, note_cents=note_cents,
            note_names=note_names, sr=ma.sr,
        )

    def _on_f0_done(self, result):
        self._f0_data = result
        self.btn_compute.setEnabled(True)
        self._lbl_status.setText("")
        self._draw_f0()
        self._redraw_cursors()

    def _on_f0_error(self, msg):
        self.btn_compute.setEnabled(True)
        self._lbl_status.setText("Error — ver log")
        self.log.emit(f"[F0 ERROR] {msg}")

    # ── dibujo ───────────────────────────────────────────────────────────────

    def _draw_f0(self):
        d          = self._f0_data
        self._plot.clear()
        self._note_lines = {}

        note_names = d['note_names']
        note_cents = d['note_cents']

        # bandas horizontales + línea central por nota
        for i, name in enumerate(note_names):
            c   = note_cents[name]
            col = _PALETTE[i % len(_PALETTE)]

            band = pg.LinearRegionItem(
                values=(c - BAND_CENTS, c + BAND_CENTS),
                orientation='horizontal',
                brush=pg.mkBrush(*col, 30),
                pen=pg.mkPen(None),
                movable=False,
            )
            self._plot.addItem(band)

            center_line = pg.InfiniteLine(
                pos=c, angle=0,
                pen=pg.mkPen(color=(*col, 180), width=1.2),
                movable=False,
            )
            self._plot.addItem(center_line)

            # etiqueta de nota sobre la línea central
            label = pg.TextItem(
                text=name, color=col, anchor=(0, 0.5),
            )
            label.setPos(0, c)
            self._plot.addItem(label)

        # curva F0
        t   = d['t']
        f0c = d['f0_cents']
        self._plot.plot(
            t, np.where(~np.isnan(f0c), f0c, np.nan),
            pen=pg.mkPen(color=(220, 60, 60), width=1.8),
            connect='finite',
        )

        # eje Y con nombres de notas
        ticks = [(note_cents[n], n) for n in note_names]
        self._plot.getAxis('left').setTicks([ticks])

        vals = list(note_cents.values())
        self._plot.setYRange(min(vals) - 120, max(vals) + 120, padding=0)

    def _redraw_cursors(self):
        """Dibuja/actualiza las InfiniteLines arrastrables para el azimuth actual."""
        if self._f0_data is None:
            return

        # quitar líneas viejas
        for lines in self._note_lines.values():
            for ln in lines.values():
                try:
                    self._plot.removeItem(ln)
                except Exception:
                    pass
        self._note_lines = {}

        if self._segments is None:
            return

        d          = self._f0_data
        sr         = d['sr']
        note_names = d['note_names']
        note_cents = d['note_cents']
        segs_az    = self._segments[self._az_idx]

        for i, name in enumerate(note_names):
            if name not in segs_az:
                continue
            seg = segs_az[name]
            col = _PALETTE[i % len(_PALETTE)]
            pen = pg.mkPen(color=(*col, 220), width=2,
                           style=Qt.PenStyle.DashLine)

            t_s = seg['start'] / sr
            t_e = seg['end']   / sr

            line_s = pg.InfiniteLine(pos=t_s, angle=90, movable=True, pen=pen)
            line_e = pg.InfiniteLine(pos=t_e, angle=90, movable=True, pen=pen)

            # Label sobre el cursor de inicio
            lbl_s = pg.TextItem(text=f'▶ {name}', color=col, anchor=(0, 1))
            lbl_s.setPos(t_s, note_cents.get(name, 0) + BAND_CENTS + 5)
            self._plot.addItem(lbl_s)

            lbl_e = pg.TextItem(text=f'{name} ◀', color=col, anchor=(1, 1))
            lbl_e.setPos(t_e, note_cents.get(name, 0) + BAND_CENTS + 5)
            self._plot.addItem(lbl_e)

            # conectar señal — capturar variables por closure
            def _make_cb(n, edge, ln, ls, le):
                def _cb(_line):
                    # mover también el TextItem correspondiente
                    t_new = ln.value()
                    if edge == 'start':
                        ls.setPos(t_new, note_cents.get(n, 0) + BAND_CENTS + 5)
                    else:
                        le.setPos(t_new, note_cents.get(n, 0) + BAND_CENTS + 5)
                    self._update_segment(n, edge, t_new)
                return _cb

            line_s.sigPositionChangeFinished.connect(_make_cb(name, 'start', line_s, lbl_s, lbl_e))
            line_e.sigPositionChangeFinished.connect(_make_cb(name, 'end',   line_e, lbl_s, lbl_e))

            self._plot.addItem(line_s)
            self._plot.addItem(line_e)
            self._note_lines[name] = {'start': line_s, 'end': line_e,
                                       'lbl_s': lbl_s, 'lbl_e': lbl_e}

    def _update_segment(self, note: str, edge: str, t_val: float):
        """Aplica el nuevo tiempo al dict de segmentos y emite la señal."""
        if self._segments is None or self._ma is None:
            return
        sr      = self._ma.sr
        sample  = max(0, int(round(t_val * sr)))
        segs_az = self._segments[self._az_idx]

        if note not in segs_az:
            segs_az[note] = {'start': 0, 'end': 0, 'purity': 1.0}

        segs_az[note][edge] = sample

        # garantizar start < end
        s, e = segs_az[note]['start'], segs_az[note]['end']
        if s >= e:
            if edge == 'start':
                segs_az[note]['start'] = max(0, e - max(1, sr // 100))
            else:
                segs_az[note]['end'] = s + max(1, sr // 100)

        az = self._ma.angles[self._az_idx]
        self.log.emit(f"[F0] {az}°  {note} {edge} → {t_val:.3f}s")
        self.segments_changed.emit(self._az_idx)
