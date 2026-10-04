"""ui/matrix_dialog.py — Herramientas ▸ Matriz de datos: mapa de calor del dato medido (azimut × elevación)."""
import numpy as np
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget, QDialogButtonBox


class _Heatmap(QWidget):
    def __init__(self, levels, azimuths, thetas, parent=None):
        super().__init__(parent)
        self._L = np.asarray(levels, dtype=float)      # (azimut, elevación)
        self._az = np.asarray(azimuths, dtype=float)
        self._th = np.asarray(thetas, dtype=float)
        self._cell = 34
        self._ml, self._mt = 110, 70                   # margen izquierdo / superior (títulos y etiquetas)
        self._vmin = float(np.nanmin(self._L))
        self._vmax = float(np.nanmax(self._L))
        n_az, n_th = len(self._az), len(self._th)
        self.setMinimumSize(QSize(self._ml + self._cell * n_az + 40, self._mt + self._cell * n_th + 40))

    def _color(self, v):
        if not np.isfinite(v):
            return QColor('#888888')
        t = min(1.0, max(0.0, (v - self._vmin) / ((self._vmax - self._vmin) or 1.0)))
        return QColor.fromRgbF(t, 0.15, 1.0 - t)     # azul (bajo) → rojo (alto)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        c, ml, mt = self._cell, self._ml, self._mt
        n_az, n_th = len(self._az), len(self._th)
        p.setFont(QFont("Segoe UI", 9))
        for i in range(n_az):
            for j in range(n_th):
                v = self._L[i, j]
                p.fillRect(ml + i * c, mt + j * c, c, c, self._color(v))
                p.setPen(QColor('#1a1a1a'))
                p.drawText(ml + i * c, mt + j * c, c, c, Qt.AlignmentFlag.AlignCenter,
                           f"{v:.0f}" if np.isfinite(v) else "—")
        # eje X: azimut (arriba de la matriz)
        p.setPen(QColor('#1a1a1a'))
        for i in range(n_az):
            p.drawText(ml + i * c, mt - 22, c, 18, Qt.AlignmentFlag.AlignCenter, f"{self._az[i]:.0f}")
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.drawText(ml, 6, c * n_az, 22, Qt.AlignmentFlag.AlignCenter, "EJE X: AZIMUT (°)")
        # eje Y: elevación (a la izquierda de la matriz)
        p.setFont(QFont("Segoe UI", 9))
        for j in range(n_th):
            p.drawText(ml - 62, mt + j * c, 56, c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{self._th[j]:.0f}°")
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.save()
        p.translate(18, mt + c * n_th / 2)
        p.rotate(-90)
        p.drawText(-c * n_th // 2, -12, c * n_th, 22, Qt.AlignmentFlag.AlignCenter,
                   "EJE Y: ELEVACIÓN θ (°)  — 0° = horizonte, 90° = cénit")
        p.restore()
        p.end()


class MatrixDialog(QDialog):
    def __init__(self, levels, azimuths, thetas, band_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Matriz de datos — {band_label}")
        self.resize(900, 720)
        lay = QVBoxLayout(self)
        intro = QLabel(
            f"Dato medido (sin suavizar ni reparar) en {band_label}. "
            "Cada celda es un punto de medición: azimut (eje X, horizontal) × elevación (eje Y, vertical).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        area = QScrollArea()
        area.setWidgetResizable(False)
        area.setWidget(_Heatmap(levels, azimuths, thetas))
        lay.addWidget(area, 1)
        row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        row.rejected.connect(self.reject)
        row.accepted.connect(self.accept)
        lay.addWidget(row)
