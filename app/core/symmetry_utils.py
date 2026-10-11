"""
core/symmetry_utils.py — Funciones compartidas para aplicar simetrías

Convención de los datos medidos: giros (azimut) de la mesa 0°–180° y micrófonos del arco vertical con elevación θ de
0° a 180° (θ = 90° es el cenit). Una misma dirección del hemisferio superior queda cubierta por una sola celda:
(θ ≤ 90°, giro g) mira hacia el azimut g, y (θ > 90°, giro g) hacia g + 180°.

Simetrías (las usan Polar 2D, Superficie 3D, Esfera y Espectro, todas con la misma función):
  'azimuth'   = izquierda ↔ derecha (plano XZ): la celda (θ, g) equivale a (180° − θ, 180° − g). Se conserva el lado
                θ ≤ 90° y se copia espejado sobre el otro; el cenit (θ = 90°) se promedia con su espejo.
  'elevation' = arriba ↔ abajo (plano XY): se agregan las elevaciones negativas como espejo de las positivas.
  'both'      = las dos.
"""
import numpy as np

_TOL = 2.0     # grados de tolerancia para encontrar la celda espejo


def _nearest(values: np.ndarray, target: float):
    """Índice del valor más cercano a `target` si está dentro de la tolerancia, si no None."""
    i = int(np.argmin(np.abs(values - target)))
    return i if abs(values[i] - target) <= _TOL else None


def _energy_mean(a, b):
    """Promedio energético de dos niveles en dB (ignora el que sea NaN)."""
    pa, pb = 10 ** (a / 10.0), 10 ** (b / 10.0)
    both = np.isfinite(a) & np.isfinite(b)
    out = np.where(both, 10 * np.log10((pa + pb) / 2.0), np.where(np.isfinite(a), a, b))
    return out


def _mirror_left_right(levels, azimuths, elevations):
    """Izquierda ↔ derecha: (θ, g) ← (180° − θ, 180° − g) para θ > 90°; el cenit se promedia con su espejo."""
    src = levels.copy()
    out = levels.copy()
    az = np.asarray(azimuths, dtype=float)
    el = np.asarray(elevations, dtype=float)
    az_pair = [_nearest(az, 180.0 - a) for a in az]
    for j, t in enumerate(el):
        if t > 90.0 + 1e-6 and abs(t - 90.0) > 1.0:
            jm = _nearest(el, 180.0 - t)
            if jm is None:
                continue
            for i, im in enumerate(az_pair):
                if im is not None:
                    out[i, j] = src[im, jm]
        elif abs(t - 90.0) <= 1.0:                       # cenit: queda simétrico respecto de sí mismo
            for i, im in enumerate(az_pair):
                if im is not None:
                    out[i, j] = _energy_mean(src[i, j], src[im, j])
    return out


def _mirror_up_down(levels, elevations):
    """Arriba ↔ abajo: agrega las elevaciones negativas; el nivel en −e es el que se midió en +e."""
    el = np.asarray(elevations, dtype=float)
    all_el = np.unique(np.concatenate([el, -el]))
    idx = []
    for ev in all_el:
        exact = np.where(np.abs(el - ev) < 1e-6)[0]
        if len(exact):
            idx.append(int(exact[0]))
        else:
            idx.append(int(np.where(np.abs(el + ev) < 1e-6)[0][0]))     # el espejo (−ev) sí está medido
    return levels[:, idx], all_el


def apply_symmetry(levels: np.ndarray, azimuths: np.ndarray,
                   elevations: np.ndarray = None,
                   symmetry_type: str = 'none'):
    """
    Aplica simetrías al patrón medido. Ver el docstring del módulo para el significado de cada una.

    Parameters
    ----------
    levels        : np.ndarray  (n_az, n_el, n_bands) o (n_az, n_el)
    azimuths      : np.ndarray  giros en grados
    elevations    : np.ndarray  elevaciones θ en grados
    symmetry_type : str         'none', 'azimuth', 'elevation', 'both'

    Returns
    -------
    (levels_sym, azimuths_sym, elevations_sym)
    """
    az = np.asarray(azimuths, dtype=np.float64).copy()
    el = np.asarray(elevations, dtype=np.float64).copy() if elevations is not None else None
    lv = np.asarray(levels).copy()
    if symmetry_type == 'none' or el is None:
        return lv, az, el

    if symmetry_type in ('azimuth', 'both'):
        lv = _mirror_left_right(lv, az, el)
    if symmetry_type in ('elevation', 'both'):
        lv, el = _mirror_up_down(lv, el)
    return lv, az, el
