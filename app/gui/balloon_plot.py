# -*- coding: utf-8 -*-
"""
BalloonPlot3D: hemisferio 3D de directividad usando pyqtgraph OpenGL.
Muestra únicamente el semi-globo medido (φ ∈ [0°, 180°]), sin espejo.
"""

from __future__ import annotations
import numpy as np

try:
    import pyqtgraph.opengl as gl
    from pyqtgraph.opengl import GLViewWidget
    _PQG_DISPONIBLE = True
except Exception:
    _PQG_DISPONIBLE = False

from scipy.interpolate import RectBivariateSpline
from scipy.ndimage import gaussian_filter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class BalloonPlot3D(QWidget):
    """
    Half-Balloon 3D: superficie hemisférica donde r = SPL normalizado.

    θ = ángulo del array (0°–180°)   → eje de elevación (Z)
    φ = ángulo de la mesa (0°–180°)  → eje azimutal, Y ≥ 0

    Se muestra solo el semi-globo medido; no se espeja al otro hemisferio.
    El eje Z apunta hacia arriba (θ = 0°), el eje Y es la normal al
    plano de corte del hemisferio.
    """

    _N_INTERP = 60   # puntos de interpolación por eje (60×60 = 3 600 verts)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not _PQG_DISPONIBLE:
            lbl = QLabel(
                "pyqtgraph / PyOpenGL no disponible.\n"
                "Instalá con:\n"
                "  pip install pyqtgraph PyOpenGL PyOpenGL_accelerate"
            )
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            self._vista = None
            return

        self._vista = GLViewWidget()
        self._vista.setBackgroundColor("#0d1117")
        # Vista inicial: hemisferio visto de frente-arriba
        self._vista.setCameraPosition(distance=3.2, elevation=25, azimuth=45)
        layout.addWidget(self._vista)

        # Ejes de referencia permanentes: X=rojo, Y=verde, Z=azul
        ejes = gl.GLAxisItem()
        ejes.setSize(x=1.2, y=1.2, z=1.2)
        self._vista.addItem(ejes)

        self._mesh: gl.GLMeshItem | None = None
        self._angulos_array: np.ndarray | None = None
        self._angulos_mesa:  np.ndarray | None = None
        self._suavizado = False

    # ── API pública ─────────────────────────────────────────────────────────

    def set_angulos(self, angulos_array: list[int], angulos_mesa: list[int]):
        self._angulos_array = np.deg2rad(angulos_array)
        self._angulos_mesa  = np.deg2rad(angulos_mesa)

    def set_suavizado(self, activo: bool):
        self._suavizado = activo

    def actualizar(self, spl_matrix: np.ndarray):
        """
        Actualiza la superficie 3D.

        Parámetros
        ----------
        spl_matrix : np.ndarray  shape (n_mics, n_angulos)
            SPL promediado sobre el tiempo para el frame y banda actuales.
        """
        if self._vista is None or self._angulos_array is None:
            return

        r       = self._preparar_radio(spl_matrix)
        X, Y, Z = self._a_cartesianas(r)
        colores  = self._colores(r)
        verts, faces = self._triangular(X, Y, Z)

        if self._mesh is not None:
            self._vista.removeItem(self._mesh)

        self._mesh = gl.GLMeshItem(
            vertexes=verts.astype(np.float32),
            faces=faces,
            vertexColors=colores,
            smooth=True,
            drawEdges=False,
        )
        self._vista.addItem(self._mesh)
        self._vista.update()   # forzar repintado

    # ── Internos ─────────────────────────────────────────────────────────────

    def _preparar_radio(self, spl: np.ndarray) -> np.ndarray:
        """
        Interpola la malla medida (n_mics × n_angulos) a N×N con
        spline bicúbica y normaliza a [0.05, 1].

        El mínimo se fija en 0.05 (no 0) para que el lóbulo de menor
        nivel siga siendo visible en la superficie.
        """
        if self._suavizado:
            spl = gaussian_filter(spl.astype(float), sigma=1.0)

        theta_orig = np.degrees(self._angulos_array)   # 0–180
        phi_orig   = np.degrees(self._angulos_mesa)    # 0–180

        spline = RectBivariateSpline(theta_orig, phi_orig, spl)

        theta_new = np.linspace(0, 180, self._N_INTERP)
        phi_new   = np.linspace(0, 180, self._N_INTERP)

        r = spline(theta_new, phi_new)

        rng = r.max() - r.min()
        if rng < 1e-6:
            return np.full_like(r, 0.5)
        # Normalizar a [0.05, 1]: el mínimo sigue siendo visible
        return 0.05 + 0.95 * (r - r.min()) / rng

    def _a_cartesianas(self, r: np.ndarray):
        """
        Convierte r(θ, φ) a (X, Y, Z) cartesianas.

        φ ∈ [0°, 180°] → Y = r·sin(θ)·sin(φ) ≥ 0  (semi-esfera Y ≥ 0).
        θ ∈ [0°, 180°] → Z va de +r (arriba) a −r (abajo).
        """
        n = self._N_INTERP
        theta = np.linspace(0, np.pi, n)        # elevación 0–π
        phi   = np.linspace(0, np.pi, n)        # azimut   0–π
        TH, PH = np.meshgrid(theta, phi, indexing="ij")
        X = r * np.sin(TH) * np.cos(PH)
        Y = r * np.sin(TH) * np.sin(PH)
        Z = r * np.cos(TH)
        return X, Y, Z

    def _colores(self, r: np.ndarray) -> np.ndarray:
        """
        Mapea r ∈ [0, 1] → RGBA usando el colormap 'plasma'.

        plasma: azul oscuro (mínimo) → violeta → naranja → amarillo (máximo).
        """
        import matplotlib.cm as cm
        rgba = cm.plasma(r.ravel())            # (N*N, 4)
        return rgba.astype(np.float32)

    @staticmethod
    def _triangular(X, Y, Z):
        """Genera vértices y caras para GLMeshItem."""
        n     = X.shape[0]
        m     = X.shape[1]
        verts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])

        faces = []
        for i in range(n - 1):
            for j in range(m - 1):
                a = i * m + j
                b = a + 1
                c = a + m
                d = c + 1
                faces.append([a, b, d])
                faces.append([a, d, c])

        return verts, np.array(faces, dtype=np.uint32)
