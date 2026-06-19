"""
core/data_store.py — Guardar y cargar resultados de directividad en NPZ.

Formato acordado:
  azimuths      (n_az,)                  ángulos azimuth en grados
  thetas        (n_thetas,)              ángulos elevación en grados
  dir_freqs     (n_bands,)               frecuencias centrales en Hz
  dir_levels    (n_az, n_thetas, n_bands) patrón polar relativo en dB (0 dB = frente)
  spl_ref       (n_bands,)               SPL absoluto en ref (az=0, theta=0)
  metadata      JSON string              ver save_results()

Sección opcional por nota (prefijo 'note_'):
  note_Fa4_dir_levels  (n_az, n_thetas, n_bands)
  note_Fa4_spl_ref     (n_bands,)
  ...
"""
import json
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Any

ISO_BANDS_HZ = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
]

ISO_BANDS_OCTAVE = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def freq_label(hz: float) -> str:
    """Etiqueta legible. 1000 → '1k', 31.5 → '31.5'"""
    if hz >= 1000:
        v = hz / 1000
        return f'{v:.4g}k'
    return f'{hz:.4g}'


def save_results(
    filepath: str,
    ma,
    notes_list: list[str] | None = None,
    bands: str = '1/3',
    threshold_spl: float = 30,
    ref_azimuth: int = 0,
    ref_theta_plot: int = 0,
) -> None:
    """
    Guarda el patrón de directividad de un MicArray en el formato NPZ acordado.

    Parameters
    ----------
    filepath       : ruta destino (.npz se agrega si falta)
    ma             : MicArray con compute_directivity() ya ejecutado
    notes_list     : lista de notas a incluir (None = todas si hay)
    bands          : resolución de bandas usada
    threshold_spl  : umbral VAD usado
    ref_azimuth    : azimuth de referencia
    ref_theta_plot : theta de referencia del plot
    """
    if ma.dir_levels is None:
        raise RuntimeError("Ejecutar compute_directivity() antes de guardar.")

    p = Path(filepath)
    if p.suffix.lower() != '.npz':
        filepath = str(p) + '.npz'

    thetas_numeric = [t for t in ma.thetas if t != 'ref']

    meta = {
        "bands":          bands,
        "threshold_spl":  threshold_spl,
        "ref_azimuth":    ref_azimuth,
        "ref_theta_plot": ref_theta_plot,
        "saved_at":       datetime.now().isoformat(timespec='seconds'),
        "notes":          [],
    }

    # Índice del theta de referencia del plot en los thetas numéricos
    i_ref_th = ma.thetas.index(ref_theta_plot) if ref_theta_plot in ma.thetas else 0
    # dir_levels ya tiene dimensión (n_az, n_thetas, n_bands), excluye 'ref'
    # Necesitamos los índices de thetas numéricos dentro del tensor completo
    theta_indices = [ma.thetas.index(t) for t in thetas_numeric]

    dir_lev = ma.dir_levels[:, theta_indices, :]  # (n_az, n_thetas_num, n_bands)

    kwargs: dict[str, Any] = dict(
        azimuths   = np.array(ma.angles, dtype=np.float32),
        thetas     = np.array(thetas_numeric, dtype=np.float32),
        dir_freqs  = ma.dir_freqs.astype(np.float32),
        dir_levels = dir_lev.astype(np.float32),
        spl_ref    = ma.dir_ref_spl.astype(np.float32),
    )

    # Notas
    if ma.notes:
        notes_to_save = notes_list or list(ma.notes.keys())
        meta["notes"] = notes_to_save
        for note_name in notes_to_save:
            ma_n = ma.notes[note_name]
            if ma_n.dir_levels is None:
                continue
            n_dir = ma_n.dir_levels[:, theta_indices, :]
            kwargs[f'note_{note_name}_dir_levels'] = n_dir.astype(np.float32)
            kwargs[f'note_{note_name}_spl_ref']    = ma_n.dir_ref_spl.astype(np.float32)

    kwargs['metadata'] = np.array([json.dumps(meta, ensure_ascii=False)])

    np.savez_compressed(filepath, **kwargs)
    size_kb = Path(filepath).stat().st_size / 1024
    print(f"  Guardado: {filepath}  ({size_kb:.0f} KB)")


def load_results(filepath: str) -> dict:
    """
    Carga un NPZ de resultados de directividad.

    Returns dict con:
        azimuths, thetas, dir_freqs, dir_levels, spl_ref, metadata
        + note_X_dir_levels, note_X_spl_ref  (si hay notas)
    """
    data = np.load(filepath, allow_pickle=False)

    required = ('azimuths', 'thetas', 'dir_freqs', 'dir_levels', 'spl_ref')
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"NPZ incompleto. Faltan: {missing}")

    result: dict = {
        'azimuths':   data['azimuths'],
        'thetas':     data['thetas'],
        'dir_freqs':  data['dir_freqs'],
        'dir_levels': data['dir_levels'],
        'spl_ref':    data['spl_ref'],
        'metadata':   {},
    }

    if 'metadata' in data:
        try:
            result['metadata'] = json.loads(str(data['metadata'][0]))
        except Exception:
            pass

    for key in data.files:
        if key.startswith('note_'):
            result[key] = data[key]

    return result
