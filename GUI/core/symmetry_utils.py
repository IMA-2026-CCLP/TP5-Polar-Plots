"""
core/symmetry_utils.py — Funciones compartidas para aplicar simetrías
"""
import numpy as np


def apply_symmetry(levels: np.ndarray, azimuths: np.ndarray, 
                  elevations: np.ndarray = None,
                  symmetry_type: str = 'none'):
    """
    Aplica simetrías: duplica mediciones a ángulos simétricos.
    Retorna arrays expandidos con ángulos simétricos incluidos.
    
    Parameters
    ----------
    levels : np.ndarray
        Datos de nivel (SPL). Puede ser (n_az, n_el, n_bands) o (n_az, n_el)
    azimuths : np.ndarray
        Ángulos azimutales en grados [0, 360)
    elevations : np.ndarray, optional
        Ángulos de elevación en grados
    symmetry_type : str
        Tipo de simetría: 'none', 'azimuth', 'elevation', 'both'
    
    Returns
    -------
    tuple
        (levels_sym, azimuths_sym, elevations_sym) con arrays expandidos
    """
    if symmetry_type == 'none':
        return levels.copy(), azimuths.copy(), elevations.copy() if elevations is not None else None
    
    levels_filled = levels.copy()
    azimuths_arr = np.asarray(azimuths, dtype=np.float64)
    elevations_arr = np.asarray(elevations, dtype=np.float64) if elevations is not None else None
    
    # Simetría azimuthal
    if symmetry_type in ['azimuth', 'both']:
        # Compute symmetric angles and reverse to align 0-360
        sym_azimuths = (360.0 - azimuths_arr) % 360.0
        sym_azimuths_reversed = sym_azimuths[::-1]
        
        # Skip first and last to avoid duplicates at boundaries
        new_azimuths = sym_azimuths_reversed[1:-1]
        new_levels = levels_filled[::-1][1:-1]
        
        # Concatenate: original + new symmetric
        azimuths_arr = np.concatenate([azimuths_arr, new_azimuths])
        levels_filled = np.concatenate([levels_filled, new_levels], axis=0)
    
    # Simetría en elevación
    if symmetry_type in ['elevation', 'both']:
        sym_elevations = -elevations_arr
        all_elevations = np.unique(np.concatenate([elevations_arr, sym_elevations]))
        
        dist = np.abs(elevations_arr[np.newaxis, :] - all_elevations[:, np.newaxis])
        map_indices = np.argmin(dist, axis=1)
        
        new_levels = levels_filled[:, map_indices, :]
        
        sym_elevations_expanded = -all_elevations
        dist_sym = np.abs(all_elevations[np.newaxis, :] - sym_elevations_expanded[:, np.newaxis])
        sym_map = np.argmin(dist_sym, axis=1)
        sym_data = new_levels[:, sym_map, :]
        
        nan_mask = np.isnan(new_levels)
        new_levels = np.where(nan_mask, sym_data, new_levels)
        
        levels_filled = new_levels
        elevations_arr = all_elevations
    
    return levels_filled, azimuths_arr, elevations_arr
