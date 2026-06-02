"""
ui/polar_plot_2d.py — Patrón polar 2D (sección transversal)
Muestra el patrón polar en un plano (elevación fija, azimut variable)
"""
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.symmetry_utils import apply_symmetry


class PolarPlot2D(QWidget):
    """
    Widget que muestra un patrón polar 2D en matplotlib.
    Inicialmente muestra la elevación = 0° (azimut variable).
    """

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 300)

        self._fixed_min = None
        self._fixed_max = None
        
        self.figure = Figure(figsize=(4, 4), dpi=100)
        self.figure.patch.set_facecolor('#1f2235')
        self.figure.subplots_adjust(top=0.82, bottom=0.1, left=0.05, right=0.95)
        self.ax = self.figure.add_subplot(111, projection='polar')
        
        self.ax.set_facecolor('#12141e')
        self.ax.grid(True, color='#2a2d3e', alpha=0.5)
        
        # Estilo
        self.ax.spines['polar'].set_color('#2a2d3e')
        self.ax.tick_params(colors='#7c8aaa', labelsize=9)
        self.ax.set_title("Patrón Polar 2D (El=0°)", color='#e8ecf4', fontsize=11, fontweight='bold')
        
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    def set_data(self, levels: np.ndarray, azimuths: np.ndarray, 
                 elevations: np.ndarray, band_index: int = 0, el_index: int = 0,
                 symmetry_type: str = 'none'):
        """
        Actualiza el plot con datos del dataset, ensamblando los 360° 
        si existen micrófonos opuestos.
        """
        # 1. Aplicar simetrías si es necesario
        levels_sym, azimuths_sym, elevations_sym = apply_symmetry(
            levels, azimuths, elevations, symmetry_type
        )
        
        if el_index >= len(elevations_sym):
            el_index = 0
            
        # 2. Extraer datos del micrófono FRONTAL (0 a 180)
        el_front = elevations_sym[el_index]
        polar_pattern_front = levels_sym[:, el_index, band_index]
        azimuths_front = azimuths_sym.copy()
        
        # 3. Buscar si existe el micrófono TRASERO (opuesto)
        el_back = (el_front + 180) % 360
        idx_back_arr = np.where(np.isclose(elevations_sym, el_back))[0]
        
        if len(idx_back_arr) > 0:
            # Si existe, extraemos sus datos y desplazamos sus ángulos 180°
            idx_back = idx_back_arr[0]
            polar_pattern_back = levels_sym[:, idx_back, band_index]
            azimuths_back = azimuths_sym + 180.0
            
            # Unimos la media vuelta frontal con la media vuelta trasera
            azimuths_full = np.concatenate([azimuths_front, azimuths_back])
            polar_pattern_full = np.concatenate([polar_pattern_front, polar_pattern_back])
            
            # Ordenamos por ángulo para que Matplotlib trace la línea prolijamente
            sort_idx = np.argsort(azimuths_full)
            azimuths_full = azimuths_full[sort_idx]
            polar_pattern_full = polar_pattern_full[sort_idx]
        else:
            # Fallback: si no hay mic opuesto, graficamos lo que haya
            azimuths_full = azimuths_front
            polar_pattern_full = polar_pattern_front

        # 4. Convertir azimut final a radianes
        azimuths_rad = np.deg2rad(azimuths_full)
        
        # 5. Normalizar respecto del valor en azimut 0°
        valid_mask = ~np.isnan(polar_pattern_full)
        if np.any(valid_mask):
            valid_indices = np.where(valid_mask)[0]
            distances_to_zero = np.abs(azimuths_full[valid_indices])
            closest_idx = valid_indices[np.argmin(distances_to_zero)]
            ref_value = polar_pattern_full[closest_idx]
        else:
            ref_value = 0.0
        
        polar_plot = polar_pattern_full - ref_value
        
        # 6. Cerrar el loop (conectar el último punto con el primero)
        azimuths_rad_closed = np.concatenate([azimuths_rad, [azimuths_rad[0]]])
        polar_plot_closed = np.concatenate([polar_plot, [polar_plot[0]]])
        
        self._last_az = azimuths_rad_closed
        self._last_r = polar_plot_closed
        self._last_el = el_front
        
        # Disparamos el dibujo
        self._redraw()

    def _redraw(self):
        """Se encarga exclusivamente de pintar usando los últimos datos guardados y los límites actuales."""
        if getattr(self, '_last_az', None) is None:
            return # Si no hay datos todavía, no hacemos nada
            
        self.ax.clear()
        
        rmin = self._fixed_min
        rmax = self._fixed_max
        
        # 1. Calcular el mínimo absoluto
        if rmin is None:
            rmin = -60 if np.isnan(self._last_r).all() else np.floor(np.nanmin(self._last_r) / 10) * 10
            
        # 2. Blindar los datos CONTRA el rmin actual (esto evita el cruce de líneas)
        polar_plot_safe = np.clip(self._last_r, a_min=rmin, a_max=None)
        
        # 3. TRAZAR Y RELLENAR PRIMERO (usando los datos seguros)
        self.ax.plot(self._last_az, polar_plot_safe, color='#5865a0', linewidth=2.5)
        self.ax.fill(self._last_az, polar_plot_safe, color='#5865a0', alpha=0.3)
        
        # 4. APLICAR LÍMITES Y ORIGEN DESPUÉS
        self.ax.set_rorigin(rmin)
        
        if self._fixed_min is not None and self._fixed_max is not None:
            self.ax.set_rlim(self._fixed_min, self._fixed_max)
            
            paso = 10 if (self._fixed_max - self._fixed_min) >= 30 else 5             
            min_tick = np.floor(self._fixed_min / paso) * paso
            max_tick = np.ceil(self._fixed_max / paso) * paso
            ticks = np.arange(min_tick, max_tick + 0.1, paso)
            
            self.ax.set_rticks(ticks)
            self.ax.set_yticklabels([f"{int(t)}" for t in ticks])
        else:
            self.ax.set_rlim(bottom=rmin)
            
        # 5. RESTAURAR ESTILO
        self.ax.set_facecolor('#12141e')
        self.ax.grid(True, color='#2a2d3e', alpha=0.5)
        self.ax.spines['polar'].set_color('#2a2d3e')
        self.ax.tick_params(colors='#7c8aaa', labelsize=9, zorder=100)
        
        self.ax.set_title(f"Patrón Polar 2D (El={self._last_el:.1f}°)", 
                         color='#e8ecf4', fontsize=11, fontweight='bold')
        
        self.ax.set_theta_zero_location('E')  # 0° a la derecha
        self.ax.set_theta_direction(1)        # Sentido antihorario        
        
        self.canvas.draw()

    # def set_band_index(self, index: int):
    #     """Cambia la banda mostrada (no recalcula, solo actualiza el plot)."""
    #     pass # MainWindow ya llama a set_data completo, esto puede quedar vacío

    def set_db_range(self, vmin, vmax):
        """Fija los límites del radio en el gráfico polar 2D y manda a repintar."""
        self._fixed_min = vmin
        self._fixed_max = vmax
        
        self._redraw()