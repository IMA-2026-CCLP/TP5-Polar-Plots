"""
ui/waveform_editor.py — Vista interactiva de ondas con cursor de onset
arrastrable, para el panel de Procesamiento.

Reemplaza el render Plotly/QWebEngineView por pyqtgraph nativo (mismo enfoque
que ui/f0_editor.py): redibujo instantáneo, zoom con la rueda y cursores
arrastrables para inspeccionar/corregir la alineación.

Requiere: pyqtgraph
"""
import numpy as np
import pyqtgraph as pg
from scipy.signal import hilbert
from scipy.fft import next_fast_len
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QSizePolicy, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont

from ui import theme as _t
from mic_array.patron import _detect_onset

# Paleta para el modo overlay (una por toma, cicla)
_OVERLAY_PALETTE = [
    (80,  140, 255), (255,  80,  80), (70,  200, 100), (255, 180,  50),
    (180, 100, 255), (50,  210, 210), (255, 220,  50), (255, 100, 220),
]

_MAX_PTS  = 3000     # puntos objetivo por traza (igual que plot_html)
_FLOOR_DB = -80.0    # piso en dB


class WaveformEditorWidget(QWidget):
    """
    Plot interactivo de las tomas del MicArray.

    Modos de vista (según `azimuth`):
      - azimuth concreto → traza única + cursor de onset arrastrable + línea
        objetivo. Arrastrar el cursor emite `onset_dragged`.
      - azimuth None ("Todos") → overlay de todas las tomas para verificar
        visualmente la alineación contra la línea objetivo.

    Señales:
        onset_dragged(int, float) — (az_idx, onset_seconds) tras soltar el cursor
        log(str)
    """
    onset_dragged = pyqtSignal(int, float)
    log           = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma            = None
        self._theta         = 'ref'
        self._azimuth       = None      # None => Todos (overlay)
        self._env           = True
        self._db            = False
        self._yrange        = None
        self._smoothing_ms  = 20.0
        # parámetros de alineación (vienen del ribbon)
        self._target_onset  = 1.0
        self._threshold_dB  = -40.0
        self._align_theta   = 'ref'
        # ítems de cursor
        self._onset_line    = None
        self._target_line   = None
        # trazas del modo overlay (para la leyenda lateral)
        self._curves        = []
        self._build_ui()

    # ── construcción ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel('bottom', 'Tiempo (s)')
        self._plot.setDownsampling(auto=True, mode='peak')
        self._plot.setClipToView(True)
        self._plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._plot, 1)

        # Barra lateral tipo leyenda: click = mostrar/ocultar, doble = aislar
        self._legend = QListWidget()
        self._legend.setFixedWidth(72)
        self._legend.setToolTip(
            "Click: mostrar/ocultar traza\nDoble click: aislar / restaurar todas"
        )
        self._legend.itemClicked.connect(self._on_legend_click)
        self._legend.itemDoubleClicked.connect(self._on_legend_double)
        self._legend.hide()
        root.addWidget(self._legend)

        self._apply_pg_theme()

    def _apply_pg_theme(self):
        p = _t.current()
        self._plot.setBackground(p['plot_bg'])
        for ax in ('bottom', 'left'):
            self._plot.getAxis(ax).setPen(pg.mkPen(p['text2']))
            self._plot.getAxis(ax).setTextPen(pg.mkPen(p['text2']))

    def apply_theme(self, palette: dict):
        self._plot.setBackground(palette['plot_bg'])
        for ax in ('bottom', 'left'):
            self._plot.getAxis(ax).setPen(pg.mkPen(palette['text2']))
            self._plot.getAxis(ax).setTextPen(pg.mkPen(palette['text2']))
        self._render()

    # ── API pública ─────────────────────────────────────────────────────────

    def set_ma(self, ma):
        self._ma = ma
        self._onset_line = None
        self._target_line = None
        self._curves = []
        self._plot.clear()
        self._legend.clear()
        self._legend.hide()

    def set_align_params(self, target_onset: float, threshold_dB: float, theta):
        """Parámetros del grupo ALINEACIÓN del ribbon — reposiciona los cursores."""
        self._target_onset = float(target_onset)
        self._threshold_dB = float(threshold_dB)
        self._align_theta  = theta
        self._render()

    def render(self, theta, azimuth, env: bool, db: bool, yrange, smoothing_ms: float = 20.0):
        """Parámetros del grupo VISTA del ribbon."""
        self._theta        = theta
        self._azimuth      = azimuth
        self._env          = env
        self._db           = db
        self._yrange       = yrange
        self._smoothing_ms = float(smoothing_ms)
        self._render()

    # ── render ────────────────────────────────────────────────────────────────

    def _prepare(self, sig: np.ndarray):
        """
        Devuelve (t, y) listos para graficar, replicando MicArray._prepare:
        - envolvente/dB: |hilbert(x)| suavizada con promedio móvil (smoothing_ms).
        - crudo: la señal tal cual.
        Luego diezma por stride para mantener ~_MAX_PTS puntos por traza.
        """
        sr     = self._ma.sr
        n      = len(sig)
        factor = max(1, n // _MAX_PTS)
        sig    = sig.astype(np.float64)

        if self._env or self._db:
            # señal analítica con FFT de longitud "rápida" → envolvente suave
            env = np.abs(hilbert(sig, N=next_fast_len(n))[:n])
            win = int(self._smoothing_ms / 1000 * sr)
            if win > 1:
                kernel = np.ones(win) / win
                env = np.convolve(env, kernel, mode='same')
            y = env[::factor]
        else:
            y = sig[::factor]

        if self._db:
            p_ref = 20e-6 if getattr(self._ma, '_is_spl', False) else 1.0
            y = np.maximum(20.0 * np.log10(np.abs(y) / p_ref + 1e-12), _FLOOR_DB)

        t = np.arange(len(y)) * factor / sr
        return t, y

    def _render(self):
        self._plot.clear()
        self._onset_line  = None
        self._target_line = None
        if self._ma is None:
            return

        ma = self._ma
        self._plot.setLabel(
            'left', 'dBFS' if self._db else ('Envolvente' if self._env else 'Amplitud')
        )

        i_th = 0
        if self._theta is not None:
            try:
                i_th = ma._th_to_col(self._theta)
            except Exception:
                i_th = 0

        self._curves = []
        ys = []
        if self._azimuth is None and self._theta is not None:
            # overlay de todas las tomas para un theta fijo
            for i in range(ma.n_angles):
                t, y = self._prepare(ma.tensor[i, i_th, :])
                ys.append(y)
                col   = _OVERLAY_PALETTE[i % len(_OVERLAY_PALETTE)]
                curve = self._plot.plot(t, y, pen=pg.mkPen(color=(*col, 150), width=1))
                self._curves.append(curve)
            self._build_legend(mode='az')
        elif self._theta is None and self._azimuth is not None:
            # overlay de todos los thetas para un azimuth fijo
            try:
                i_az = ma._az_to_row(self._azimuth)
            except Exception:
                return
            for i_th_idx in range(ma.n_thetas):
                t, y = self._prepare(ma.tensor[i_az, i_th_idx, :])
                ys.append(y)
                col   = _OVERLAY_PALETTE[i_th_idx % len(_OVERLAY_PALETTE)]
                curve = self._plot.plot(t, y, pen=pg.mkPen(color=(*col, 150), width=1))
                self._curves.append(curve)
            self._build_legend(mode='th')
        else:
            try:
                i_az = ma._az_to_row(self._azimuth)
            except Exception:
                return
            t, y = self._prepare(ma.tensor[i_az, i_th, :])
            ys.append(y)
            p = _t.current()
            self._plot.plot(t, y, pen=pg.mkPen(p['accent'], width=1))
            self._legend.clear()
            self._legend.hide()

        self._apply_yrange(ys)
        self._draw_cursors()

    # ── leyenda lateral interactiva ───────────────────────────────────────────

    def _build_legend(self, mode: str = 'az'):
        self._legend.clear()
        if mode == 'az':
            labels = [f"{a}°" for a in self._ma.angles]
        else:  # 'th'
            labels = ["ref" if t == "ref" else f"{t}°" for t in self._ma.thetas]
        for i, lbl in enumerate(labels):
            col  = _OVERLAY_PALETTE[i % len(_OVERLAY_PALETTE)]
            item = QListWidgetItem(lbl)
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setForeground(QColor(*col))
            self._legend.addItem(item)
        self._legend.show()

    def _style_legend_item(self, i: int, visible: bool):
        item = self._legend.item(i)
        if item is None:
            return
        col = _OVERLAY_PALETTE[i % len(_OVERLAY_PALETTE)]
        item.setForeground(QColor(*col) if visible else QColor('#6b7280'))
        font = item.font()
        font.setStrikeOut(not visible)
        item.setFont(font)

    def _on_legend_click(self, item: QListWidgetItem):
        i = item.data(Qt.ItemDataRole.UserRole)
        if i is None or i >= len(self._curves):
            return
        visible = not self._curves[i].isVisible()
        self._curves[i].setVisible(visible)
        self._style_legend_item(i, visible)

    def _on_legend_double(self, item: QListWidgetItem):
        i = item.data(Qt.ItemDataRole.UserRole)
        if i is None or i >= len(self._curves):
            return
        isolated = (
            self._curves[i].isVisible()
            and all(not c.isVisible() for j, c in enumerate(self._curves) if j != i)
        )
        # Si ya está aislada → restaurar todas; si no → mostrar solo esta
        for j, c in enumerate(self._curves):
            vis = True if isolated else (j == i)
            c.setVisible(vis)
            self._style_legend_item(j, vis)

    def _apply_yrange(self, ys):
        if self._yrange:
            self._plot.setYRange(self._yrange[0], self._yrange[1], padding=0)
            return
        # En dB, ignorar el piso de ruido para que la señal útil llene el eje
        if self._db and ys:
            allv = np.concatenate(ys)
            sig_v = allv[allv > _FLOOR_DB + 3]
            if len(sig_v):
                y_min = float(np.percentile(sig_v, 5))
                y_max = float(allv.max())
                margin = (y_max - y_min) * 0.05 or 1.0
                self._plot.setYRange(y_min - margin, y_max + margin, padding=0)
                return
        self._plot.enableAutoRange(axis='y')

    # ── cursores ────────────────────────────────────────────────────────────

    def _draw_cursors(self):
        if self._ma is None:
            return
        p = _t.current()

        # línea objetivo (siempre, también en overlay para verificar)
        self._target_line = pg.InfiniteLine(
            pos=self._target_onset, angle=90, movable=False,
            pen=pg.mkPen(p['text_muted'], width=1, style=Qt.PenStyle.DashLine),
            label='objetivo', labelOpts={'position': 0.04, 'color': p['text_muted']},
        )
        self._plot.addItem(self._target_line)

        # cursor de onset arrastrable solo con una toma seleccionada
        if self._azimuth is None:
            return
        try:
            i_az = self._ma._az_to_row(self._azimuth)
            i_th = self._ma._th_to_col(self._align_theta)
        except Exception:
            return

        sig      = self._ma.tensor[i_az, i_th, :].astype(np.float64)
        onset_s  = _detect_onset(sig, self._ma.sr, threshold_dB=self._threshold_dB) / self._ma.sr

        self._onset_line = pg.InfiniteLine(
            pos=onset_s, angle=90, movable=True,
            pen=pg.mkPen(p['accent'], width=2),
            hoverPen=pg.mkPen(p['accent'], width=3),
            label='onset', labelOpts={'position': 0.92, 'color': p['accent']},
        )
        self._onset_line.sigPositionChangeFinished.connect(self._on_onset_drag)
        self._plot.addItem(self._onset_line)

    def _on_onset_drag(self, line):
        if self._ma is None or self._azimuth is None:
            return
        try:
            i_az = self._ma._az_to_row(self._azimuth)
        except Exception:
            return
        t = float(line.value())
        self.onset_dragged.emit(i_az, t)
