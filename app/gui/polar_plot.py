# -*- coding: utf-8 -*-
"""
PolarPlot2D: gráfico polar de directividad embebido en Qt.
Usa matplotlib FigureCanvas.
"""

from __future__ import annotations
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class PolarPlot2D(FigureCanvas):
    """
    Gráfico polar animado.

    Eje angular: ángulo del array (0°–180°), espejado a 360°.
    Radio:       SPL normalizado al máximo del frame.
    Punto naranja en el ángulo de máxima energía.
    """

    def __init__(self, parent=None):
        fig = Figure(figsize=(5, 5), facecolor="#1a1a2e")
        super().__init__(fig)
        self.setParent(parent)

        self._ax = fig.add_subplot(111, projection="polar")
        self._configurar_ejes()

        self._linea,   = self._ax.plot([], [], color="#00d4ff", linewidth=2)
        self._fill     = None
        self._punto,   = self._ax.plot([], [], "o", color="#ff8c00",
                                        markersize=10, zorder=5)
        self._angulos_rad: np.ndarray | None = None

    # ── API pública ─────────────────────────────────────────────────────────

    def set_angulos(self, angulos_grados: list[int]):
        """Define los ángulos del array (se llama una vez al cargar la sesión)."""
        ang = np.array(angulos_grados, dtype=float)
        # Espejado: 0°–180° + 180°–360° (sentido inverso para cerrar el patrón)
        self._angulos_rad = np.deg2rad(
            np.concatenate([ang, 360 - ang[::-1]])
        )

    def actualizar(self, spl_array: np.ndarray):
        """
        Actualiza el gráfico con un nuevo frame.

        Parámetros
        ----------
        spl_array : np.ndarray  shape (n_mics,)
            SPL promediado sobre todos los ángulos de mesa para el frame actual.
        """
        if self._angulos_rad is None or len(spl_array) == 0:
            return

        # Espejo
        spl = np.concatenate([spl_array, spl_array[::-1]])
        spl_norm = self._normalizar(spl)

        ang = self._angulos_rad
        if len(ang) != len(spl_norm):
            return

        # Cerrar el polígono
        ang_c  = np.append(ang, ang[0])
        spl_c  = np.append(spl_norm, spl_norm[0])

        self._linea.set_data(ang_c, spl_c)

        # Relleno
        if self._fill:
            self._fill.remove()
        self._fill = self._ax.fill(ang_c, spl_c, alpha=0.15, color="#00d4ff")

        # Punto de máximo
        idx_max  = int(np.argmax(spl_norm[:len(spl_array)]))
        ang_max  = self._angulos_rad[idx_max]
        self._punto.set_data([ang_max], [spl_norm[idx_max]])

        self.draw()

    # ── Internos ─────────────────────────────────────────────────────────────

    def _configurar_ejes(self):
        ax = self._ax
        ax.set_facecolor("#1a1a2e")
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.tick_params(colors="#aaaaaa", labelsize=8)
        ax.spines["polar"].set_color("#444466")
        ax.grid(color="#333355", linestyle="--", linewidth=0.5)
        ax.set_rlabel_position(45)
        for spine in ax.spines.values():
            spine.set_color("#444466")

    @staticmethod
    def _normalizar(spl: np.ndarray) -> np.ndarray:
        mx = spl.max()
        mn = spl.min()
        rng = mx - mn
        if rng < 1e-6:
            return np.ones_like(spl) * 0.5
        return (spl - mn) / rng
