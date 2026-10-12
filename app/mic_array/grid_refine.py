"""Suavizado e interpolación de la grilla (θ × giro) para la matriz radial, por banda, en dB.

- Suavizado: cambia los valores medidos para quitar ruido (gaussiano, Savitzky-Golay, media móvil).
- Interpolación: estima valores entre las mediciones (lineal o bicúbica) y afina la grilla a `step` grados.
  No cambia las mediciones; sólo agrega puntos entre ellas.
"""
import numpy as np
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.signal import savgol_filter
from scipy.interpolate import RegularGridInterpolator, RectBivariateSpline

SMOOTH_METHODS = ('ninguno', 'gaussiano', 'savgol', 'media móvil')
INTERP_METHODS = ('lineal', 'bicúbica')


def smooth(levels, method, intensity):
    """levels: (n_az, n_th, nb). intensity: puntos vecinos (0 = sin suavizar)."""
    if method == 'ninguno' or not intensity:
        return np.asarray(levels, dtype=float)
    k = int(intensity)
    w = 2 * k + 1
    out = np.array(levels, dtype=float)
    for b in range(out.shape[2]):
        x = out[:, :, b]
        for ax in (0, 1):
            n = x.shape[ax]
            if method == 'gaussiano':
                x = gaussian_filter1d(x, sigma=k / 2.0, axis=ax, mode='nearest')
            elif method == 'savgol' and 3 <= w <= n:
                x = savgol_filter(x, w, 2, axis=ax, mode='nearest')
            elif method == 'media móvil' and w <= n:
                x = uniform_filter1d(x, size=w, axis=ax, mode='nearest')
        out[:, :, b] = x
    return out


def _evaluate(levels, az, th, method, az_f, th_f):
    """Evalúa la interpolación (lineal o bicúbica) de levels (az × th × nb) en la malla az_f × th_f."""
    AZ, TH = np.meshgrid(az_f, th_f, indexing='ij')
    pts = np.stack([AZ.ravel(), TH.ravel()], axis=-1)
    out = np.empty((len(az_f), len(th_f), levels.shape[2]))
    for b in range(levels.shape[2]):
        z = levels[:, :, b]
        if method == 'lineal' or np.isnan(z).any():     # con huecos (NaN) la bicúbica no sirve
            f = RegularGridInterpolator((az, th), z, method='linear', bounds_error=False, fill_value=None)
            out[:, :, b] = f(pts).reshape(AZ.shape)
        else:
            out[:, :, b] = RectBivariateSpline(az, th, z, kx=3, ky=3)(az_f, th_f)
    return out


def interpolate(levels, az, th, method, step):
    """Afina la grilla (azimut × θ) a `step` grados desde las mediciones, con método lineal o bicúbica.
    step = 0 (ninguna), o un paso ≥ al medido: devuelve la grilla original sin cambios.
    Devuelve (levels_out, az_out, th_out)."""
    az = np.asarray(az, dtype=float)
    th = np.asarray(th, dtype=float)
    levels = np.asarray(levels, dtype=float)
    ia, it = np.argsort(az), np.argsort(th)
    az, th, levels = az[ia], th[it], levels[ia][:, it]
    native = float(min(np.min(np.diff(az)), np.min(np.diff(th)))) if len(az) > 1 and len(th) > 1 else 0.0
    if step <= 0 or step >= native:
        return levels, az, th
    az_f = np.arange(az[0], az[-1] + 1e-9, step)
    th_f = np.arange(th[0], th[-1] + 1e-9, step)
    return _evaluate(levels, az, th, method, az_f, th_f), az_f, th_f
