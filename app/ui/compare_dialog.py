"""ui/compare_dialog.py — Herramientas ▸ Comparar mediciones: superpone señales en el tiempo de los micrófonos
elegidos, para un giro dado. Lee el audio en memoria (incluye reemplazos por espejo aplicados)."""
import numpy as np
import pyqtgraph as pg
from scipy.signal import hilbert
from scipy.fft import next_fast_len
from ui.waveform_editor import _MAX_PTS, _FLOOR_DB
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QListWidget,
                             QListWidgetItem, QDialogButtonBox)

COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf',
          '#bcbd22', '#7f7f7f', '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5', '#c49c94',
          '#f7b6d2', '#c7c7c7', '#dbdb8d']


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class CompareDialog(QDialog):
    def __init__(self, ma_getter, view_params=None, pairs=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comparar mediciones")
        self.resize(960, 600)
        self._pairs = pairs            # [(θ, giro), ...] desde la matriz; si viene, se usa en vez de las casillas
        self._get = ma_getter
        self._view = view_params or (lambda: {'env': True, 'db': False, 'smooth': 20.0, 'yrange': None})
        self._ma = ma_getter()
        lay = QVBoxLayout(self)
        if self._ma is None or getattr(self._ma, 'tensor', None) is None:
            lay.addWidget(QLabel("No hay audio cargado. Cargá los WAV para comparar mediciones."))
            row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            row.rejected.connect(self.reject)
            lay.addWidget(row)
            return

        top = QHBoxLayout()
        top.addWidget(QLabel("Distancia al cénit d (°):"))
        self._d = QComboBox()
        for d in range(0, 91, 10):
            self._d.addItem(f"d = {d}°" + ("  (cénit, mic 10)" if d == 0 else ""), d)
        self._d.currentIndexChanged.connect(self._on_d)
        top.addWidget(self._d)
        top.addSpacing(20)
        top.addWidget(QLabel("Giro (HOR):"))
        self._giro = QComboBox()
        for g in self._ma.angles:
            gv = _num(g)
            if gv is not None:
                self._giro.addItem(f"{gv:.0f}°", gv)
        self._giro.currentIndexChanged.connect(self._redraw)
        top.addWidget(self._giro)
        top.addStretch(1)
        lay.addLayout(top)

        body = QHBoxLayout()
        self._plot = pg.PlotWidget()
        self._plot.setBackground('w')
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel('bottom', 'tiempo', units='s')
        self._plot.addLegend()
        body.addWidget(self._plot, 1)

        side = QVBoxLayout()
        side.addWidget(QLabel("Micrófonos a mostrar:"))
        self._list = QListWidget()
        self._items = {}
        for t in self._ma.thetas:
            tv = _num(t)
            if tv is None:
                continue
            k = int(round(tv / 10)) + 1
            it = QListWidgetItem(f"mic {k}  (θ = {tv:.0f}°)")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, tv)
            self._list.addItem(it)
            self._items[tv] = it
        self._list.itemChanged.connect(self._redraw)
        side.addWidget(self._list, 1)
        body.addLayout(side)
        lay.addLayout(body, 1)

        row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        row.rejected.connect(self.reject)
        lay.addWidget(row)
        self._on_d()

    def _on_d(self, _=None):
        """Marca los micrófonos del anillo elegido (θ = 90 − d y 90 + d). No desmarca lo que ya elegiste."""
        d = self._d.currentData()
        targets = {90.0} if d == 0 else {90.0 - d, 90.0 + d}
        self._list.blockSignals(True)
        for tv in targets:
            if tv in self._items:
                self._items[tv].setCheckState(Qt.CheckState.Checked)
        self._list.blockSignals(False)
        self._redraw()

    def _redraw(self, *_):
        ma = self._get()
        if ma is None or getattr(ma, 'tensor', None) is None:
            return
        self._plot.clear()
        try:
            self._plot.addLegend()
        except Exception:
            pass
        v = self._view()
        if self._pairs is not None:
            todo = list(self._pairs)                       # (θ, giro) de la matriz
        else:
            giro = self._giro.currentData()
            todo = [(tv, giro) for tv, it in self._items.items() if it.checkState() == Qt.CheckState.Checked]
        k = 0
        for tv, giro in todo:
            ia = int(np.argmin(np.abs(np.asarray([_num(a) or 0 for a in ma.angles]) - (giro or 0))))
            j = [i for i, t in enumerate(ma.thetas) if _num(t) is not None and abs(_num(t) - tv) < 0.5]
            if not j:
                continue
            t, y = self._prepare(ma, ma.tensor[ia, j[0], :], v['env'], v['db'], v['smooth'])
            kk = int(round(tv / 10)) + 1
            self._plot.plot(t, y, pen=pg.mkPen(COLORS[k % len(COLORS)], width=1.2),
                            name=f"mic {kk} · {tv:.0f}° · giro {giro:.0f}°")
            k += 1
        self._plot.setLabel('left', 'dB' if v['db'] else 'amplitud')
        if v.get('yrange'):
            self._plot.setYRange(v['yrange'][0], v['yrange'][1], padding=0)
        else:
            self._plot.enableAutoRange(axis='y')

    @staticmethod
    def _prepare(ma, sig, env, db, smooth_ms):
        """Igual que WaveformEditorWidget._prepare: envolvente (Hilbert + promedio móvil) o señal cruda,
        en dB si corresponde, diezmada a ~_MAX_PTS puntos."""
        sr = ma.sr
        n = len(sig)
        factor = max(1, n // _MAX_PTS)
        sig = np.asarray(sig, dtype=np.float64)
        if env or db:
            e = np.abs(hilbert(sig, N=next_fast_len(n))[:n])
            win = int(smooth_ms / 1000 * sr)
            if win > 1:
                e = np.convolve(e, np.ones(win) / win, mode='same')
            y = e[::factor]
        else:
            y = sig[::factor]
        if db:
            p_ref = 20e-6 if getattr(ma, '_is_spl', False) else 1.0
            y = np.maximum(20.0 * np.log10(np.abs(y) / p_ref + 1e-12), _FLOOR_DB)
        t = np.arange(len(y)) * factor / sr
        return t, y
