"""
core/session.py — Guardar y cargar sesiones .cclp.

Un .cclp es un NPZ renombrado que contiene TODO el estado de trabajo:
  - Tensor procesado (en unidades FS, con SPL revertido antes de guardar)
  - Metadatos del array (sr, azimuth, theta, calibración, flag is_spl)
  - Directividad calculada (dir_levels, dir_freqs, dir_ref_spl) si existe
  - Notas extraídas (tensor por nota, dir por nota si existe)
  - Parámetros de UI (onset, umbral, smoothing, etc.) como JSON
"""
import json
import numpy as np
from pathlib import Path
from datetime import datetime


def save_cclp(path: str, ma, ui_state: dict | None = None) -> None:
    """
    Guarda la sesión completa en un archivo .cclp.

    Parameters
    ----------
    path      : ruta destino (se fuerza extensión .cclp)
    ma        : MicArray con el estado actual
    ui_state  : dict con los valores del ribbon (state del Bridge)
    """
    path = Path(path).with_suffix('.cclp')
    path.parent.mkdir(parents=True, exist_ok=True)

    # ── Tensor: deshacer SPL antes de guardar (igual que MicArray.save) ────
    tensor_to_save = ma.tensor
    if ma._is_spl and ma.calibration is not None:
        scale = 20e-6 * 10 ** (ma.calibration / 20)
        tensor_to_save = ma.tensor / scale[np.newaxis, :, np.newaxis]

    kwargs: dict = dict(
        tensor    = tensor_to_save.astype(np.float32),
        sr        = np.array(ma.sr),
        azimuth   = np.array(ma.angles, dtype=np.float32),
        theta     = np.array(ma.thetas, dtype=object),
        is_spl    = np.array(ma._is_spl),
    )

    if ma.calibration is not None:
        kwargs['calibration'] = ma.calibration.astype(np.float32)

    # ── Directividad global ────────────────────────────────────────────────
    if ma.dir_levels is not None:
        kwargs['dir_levels']  = ma.dir_levels.astype(np.float32)
        kwargs['dir_freqs']   = ma.dir_freqs.astype(np.float32)
        kwargs['dir_ref_spl'] = ma.dir_ref_spl.astype(np.float32)

    # ── Notas ──────────────────────────────────────────────────────────────
    if ma.notes:
        note_names = list(ma.notes.keys())
        for note_name, ma_n in ma.notes.items():
            kwargs[f'note_{note_name}_tensor'] = ma_n.tensor.astype(np.float32)
            if ma_n.dir_levels is not None:
                kwargs[f'note_{note_name}_dir_levels'] = ma_n.dir_levels.astype(np.float32)
                kwargs[f'note_{note_name}_dir_ref_spl'] = ma_n.dir_ref_spl.astype(np.float32)
    else:
        note_names = []

    # ── Parámetros de UI + metadata ────────────────────────────────────────
    meta = {
        'saved_at':  datetime.now().isoformat(timespec='seconds'),
        'notes':     note_names,
        'ui_state':  ui_state or {},
    }
    kwargs['session_params'] = np.array([json.dumps(meta, ensure_ascii=False)])

    np.savez_compressed(str(path), **kwargs)
    size_kb = path.stat().st_size / 1024
    print(f"  Sesión guardada: {path}  ({size_kb:.0f} KB)")


def load_cclp(path: str):
    """
    Carga una sesión .cclp y devuelve (ma, ui_state).

    Returns
    -------
    ma        : MicArray reconstruido con todo el estado
    ui_state  : dict con los parámetros de UI guardados (puede ser {})
    """
    from mic_array.patron import MicArray

    path = Path(path)
    data = np.load(str(path), allow_pickle=True)

    # ── MicArray base ──────────────────────────────────────────────────────
    tensor = data['tensor']
    sr     = int(data['sr'])
    angles = data['azimuth'].tolist()
    thetas = data['theta'].tolist()

    ma = MicArray(tensor, sr=sr, angles=angles, thetas=thetas)

    if 'calibration' in data:
        ma.calibration = data['calibration']

    ma._is_spl = bool(data['is_spl']) if 'is_spl' in data else False

    # ── Directividad global ────────────────────────────────────────────────
    if 'dir_levels' in data:
        ma.dir_levels  = data['dir_levels']
        ma.dir_freqs   = data['dir_freqs']
        ma.dir_ref_spl = data['dir_ref_spl']

    # ── Notas ──────────────────────────────────────────────────────────────
    note_keys = [k[5:-7] for k in data.files if k.startswith('note_') and k.endswith('_tensor')]
    if note_keys:
        ma.notes = {}
        for note_name in note_keys:
            ma_n = MicArray(
                data[f'note_{note_name}_tensor'],
                sr=sr, angles=angles, thetas=thetas,
            )
            ma_n.calibration = ma.calibration
            ma_n._is_spl     = ma._is_spl
            if f'note_{note_name}_dir_levels' in data:
                ma_n.dir_levels  = data[f'note_{note_name}_dir_levels']
                ma_n.dir_freqs   = ma.dir_freqs
                ma_n.dir_ref_spl = data[f'note_{note_name}_dir_ref_spl']
            ma.notes[note_name] = ma_n

    # ── Parámetros de UI ───────────────────────────────────────────────────
    ui_state = {}
    if 'session_params' in data:
        try:
            meta     = json.loads(str(data['session_params'][0]))
            ui_state = meta.get('ui_state', {})
        except Exception:
            pass

    return ma, ui_state
