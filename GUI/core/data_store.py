"""
core/data_store.py — NPZ save/load for polar pattern data
═══════════════════════════════════════════════════════════
Estructura del archivo .npz
───────────────────────────
  levels     : float32  (n_az, n_el, n_bands)  — dB SPL
  azimuths   : float32  (n_az,)                — grados
  elevations : float32  (n_el,)                — grados
  bands      : float32  (n_bands,)             — Hz (frec. central)
  metadata   : array([JSON string])            — info de procesamiento
"""
import json
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# ─── Bandas estándar ISO 266 ──────────────────────────────────────────────────
ISO_BANDS_HZ = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
]

ISO_BANDS_OCTAVE = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def freq_label(hz: float) -> str:
    """Etiqueta legible de frecuencia. Ej: 31.5 → '31.5 Hz', 1000 → '1k Hz'"""
    if hz >= 1000:
        v = hz / 1000
        s = f'{v:.4g}'
        return f'{s}k'
    return f'{hz:.4g}'


def save_polar(
    filepath: str,
    levels: np.ndarray,
    azimuths: np.ndarray,
    elevations: np.ndarray,
    bands: np.ndarray,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Guarda datos de patrón polar en formato NPZ comprimido.

    Args:
        filepath : ruta destino (se agrega .npz si no tiene extensión)
        levels   : (n_az, n_el, n_bands) array de dB SPL
        azimuths : (n_az,) ángulos de azimut en grados
        elevations: (n_el,) ángulos de elevación en grados
        bands    : (n_bands,) frecuencias centrales en Hz
    """
    p = Path(filepath)
    if p.suffix.lower() != '.npz':
        filepath = str(p) + '.npz'

    meta = dict(metadata or {})
    meta.update({
        'saved_at': datetime.now().isoformat(timespec='seconds'),
        'shape_n_az': int(levels.shape[0]),
        'shape_n_el': int(levels.shape[1]),
        'shape_n_bands': int(levels.shape[2]),
        'az_range': [float(azimuths.min()), float(azimuths.max())],
        'el_range': [float(elevations.min()), float(elevations.max())],
        'band_range': [float(bands.min()), float(bands.max())],
    })

    np.savez_compressed(
        filepath,
        levels=levels.astype(np.float32),
        azimuths=azimuths.astype(np.float32),
        elevations=elevations.astype(np.float32),
        bands=bands.astype(np.float32),
        metadata=np.array([json.dumps(meta, ensure_ascii=False)]),
    )


def load_polar(filepath: str) -> Dict[str, Any]:
    """
    Carga un archivo NPZ de patrón polar.

    Returns dict con claves:
        levels, azimuths, elevations, bands, metadata
    """
    data = np.load(filepath, allow_pickle=False)

    required = ('levels', 'azimuths', 'elevations', 'bands')
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Archivo NPZ incompleto. Faltan: {missing}")

    result: Dict[str, Any] = {
        'levels': data['levels'],
        'azimuths': data['azimuths'],
        'elevations': data['elevations'],
        'bands': data['bands'],
        'metadata': {},
    }

    if 'metadata' in data:
        try:
            result['metadata'] = json.loads(str(data['metadata'][0]))
        except Exception:
            pass

    return result
