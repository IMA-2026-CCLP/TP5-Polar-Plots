"""ui/matrix_dialog.py — Herramientas ▸ Matriz de datos: mapa de calor del dato medido (azimut × elevación)."""
import os
import numpy as np
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QDialogButtonBox, QToolTip, QPushButton

_ML, _MT = 90, 60   # margen izquierdo / superior (rótulos de ejes)


class _Heatmap(QWidget):
    def __init__(self, levels, azimuths, thetas, source=None, on_click=None, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self._L = np.asarray(levels, dtype=float)      # (azimut, elevación)
        self._az = np.asarray(azimuths, dtype=float)
        self._th = np.asarray(thetas, dtype=float)
        self._source = source
        self._cell = 30
        self._vmin = float(np.nanmin(self._L))
        self._vmax = float(np.nanmax(self._L))
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(420, 360))

    def _fit(self):
        """Celda que entra en el área disponible (la matriz nunca se sale de la ventana)."""
        n_az, n_th = len(self._az), len(self._th)
        c = min((self.width() - _ML - 20) / n_az, (self.height() - _MT - 20) / n_th)
        self._cell = max(8, int(c))

    def resizeEvent(self, _):
        self._fit()

    def _color(self, v):
        if not np.isfinite(v):
            return QColor('#888888')
        t = min(1.0, max(0.0, (v - self._vmin) / ((self._vmax - self._vmin) or 1.0)))
        return QColor.fromRgbF(t, 0.15, 1.0 - t)     # azul (bajo) → rojo (alto)

    def _cell_at(self, pos):
        i = int((pos.x() - _ML) // self._cell)
        j = int((pos.y() - _MT) // self._cell)
        if 0 <= i < len(self._az) and 0 <= j < len(self._th):
            return i, j
        return None

    def mousePressEvent(self, ev):
        hit = self._cell_at(ev.position().toPoint())
        if hit is not None and self._on_click is not None:
            i, j = hit
            msg = self._on_click(float(self._az[i]), float(self._th[j]))
            if msg:
                QToolTip.showText(ev.globalPosition().toPoint(), msg, self)

    def mouseMoveEvent(self, ev):
        hit = self._cell_at(ev.position().toPoint())
        if hit is None:
            QToolTip.hideText()
            return
        i, j = hit
        if isinstance(self._source, dict):          # matriz desde audios: un WAV por toma
            full = self._source.get((float(self._az[i]), float(self._th[j])), "—")
            name = os.path.basename(full) if full != "—" else "sin archivo"
        else:
            name = os.path.basename(self._source) if self._source else "cálculo desde audio (sin archivo)"
            full = self._source or "—"
        v = self._L[i, j]
        text = (f"Archivo: {name}\n"
                f"Azimut: {self._az[i]:.0f}°   Elevación: {self._th[j]:.0f}°\n"
                f"Nivel: {v:.1f} dB" if np.isfinite(v) else f"Archivo: {name}\nSin dato")
        QToolTip.showText(ev.globalPosition().toPoint(), text, self)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        c = self._cell
        n_az, n_th = len(self._az), len(self._th)
        p.setFont(QFont("Segoe UI", max(6, min(9, c // 3))))
        for i in range(n_az):
            for j in range(n_th):
                v = self._L[i, j]
                p.fillRect(_ML + i * c, _MT + j * c, c, c, self._color(v))
                p.setPen(QColor('#1a1a1a'))
                p.drawText(_ML + i * c, _MT + j * c, c, c, Qt.AlignmentFlag.AlignCenter,
                           f"{v:.0f}" if np.isfinite(v) else "—")
        # eje X: azimut (arriba)
        p.setPen(QColor('#1a1a1a'))
        p.setFont(QFont("Segoe UI", max(6, min(9, c // 3))))
        for i in range(n_az):
            p.drawText(_ML + i * c, _MT - 20, c, 16, Qt.AlignmentFlag.AlignCenter, f"{self._az[i]:.0f}")
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(_ML, 4, c * n_az, 20, Qt.AlignmentFlag.AlignCenter, "EJE X: AZIMUT (°)")
        # eje Y: elevación (izquierda, vertical)
        p.setFont(QFont("Segoe UI", max(6, min(9, c // 3))))
        for j in range(n_th):
            p.drawText(_ML - 50, _MT + j * c, 44, c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{self._th[j]:.0f}°")
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.save()
        p.translate(14, _MT + c * n_th / 2)
        p.rotate(-90)
        p.drawText(-c * n_th // 2, -10, c * n_th, 20, Qt.AlignmentFlag.AlignCenter,
                   "EJE Y: ELEVACIÓN θ (°)  — 0° = horizonte, 90° = cénit")
        p.restore()
        p.end()


class MatrixDialog(QDialog):
    def _stop_audio(self):
        from ui.audio_play import stop
        stop()
        self._status.setText("Reproducción detenida.")

    def __init__(self, levels, azimuths, thetas, band_label: str, source=None, on_click=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Matriz de datos — {band_label}")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        if isinstance(source, dict):
            origin = "archivos WAV de audio (uno por toma)"
        else:
            origin = os.path.basename(source) if source else "cálculo desde audio"
        intro = QLabel(
            f"Dato medido (sin suavizar ni reparar) · {band_label} · origen: {origin}. "
            "Pasá el mouse sobre una celda para ver el archivo de origen. Click en una celda: reproduce esa toma (si hay audio cargado).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        def _click(az, th):
            msg = on_click(az, th) if on_click is not None else ""
            self._status.setText(msg or "")
            return msg
        self._heat = _Heatmap(levels, azimuths, thetas, source, on_click=_click if on_click else None)
        lay.addWidget(self._heat, 1)
        bar = QHBoxLayout()
        self._status = QLabel("Click en una celda para escuchar esa toma.")
        bar.addWidget(self._status, 1)
        b_stop = QPushButton("■ Detener")
        b_stop.clicked.connect(self._stop_audio)
        bar.addWidget(b_stop)
        lay.addLayout(bar)
        row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        row.rejected.connect(self.reject)
        row.accepted.connect(self.accept)
        lay.addWidget(row)
