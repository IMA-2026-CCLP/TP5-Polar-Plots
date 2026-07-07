"""
core/data_store.py — Guardar y cargar resultados de directividad en NPZ.

Formato acordado:
  azimuths        (n_az,)                  ángulos azimuth en grados
  thetas          (n_thetas,)              ángulos elevación en grados
  dir_freqs       (n_bands,)               frecuencias centrales en Hz
  dir_levels      (n_az, n_thetas, n_bands) patrón polar relativo en dB (0 dB = frente)
  spl_ref         (n_bands,)               SPL absoluto en ref (az=0, theta=0), "igualado"
  spl_ref_per_az  (n_az, n_bands)          SPL absoluto del mic ref por toma, "original"
                                           (para el panel Espectro). Ausente en NPZ viejos.
  metadata        JSON string              ver save_results()

Sección opcional por nota (prefijo 'note_'):
  note_Fa4_dir_levels        (n_az, n_thetas, n_bands)
  note_Fa4_spl_ref           (n_bands,)
  note_Fa4_spl_ref_per_az    (n_az, n_bands)
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


def _spl_ref_per_azimuth(ma) -> np.ndarray | None:
    """
    Reconstruye el SPL absoluto del mic de referencia por toma angular
    (espectro "original", sin igualar), idéntico al cálculo de
    TabDirectividad._show_results() para el panel Espectro.
    """
    if 'ref' in ma.thetas and ma.dir_ref_spl is not None and getattr(ma, 'dir_delta', None) is not None:
        i_ref = ma.thetas.index('ref')
        base  = (ma.dir_levels[0, i_ref, :] + ma.dir_ref_spl).astype(np.float32)
        return (base[np.newaxis, :] - ma.dir_delta).astype(np.float32)
    if ma.dir_ref_spl is not None:
        return np.tile(ma.dir_ref_spl, (len(ma.angles), 1)).astype(np.float32)
    return None


def save_results(
    filepath: str,
    ma,
    notes_list: list[str] | None = None,
    bands: str = '1/3',
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
    ref_azimuth    : azimuth de referencia
    ref_theta_plot : theta de referencia del plot
    """
    notes_to_save = notes_list or (list(ma.notes.keys()) if ma.notes else [])
    notes_to_save = [n for n in notes_to_save
                     if ma.notes and ma.notes[n].dir_levels is not None]

    # Si nunca se computó la directividad "global" (modo "Todo el audio")
    # pero sí se computaron notas individuales, usar la primera nota
    # computada como fuente de los campos "globales" del NPZ (dir_levels,
    # spl_ref, etc.) — así el archivo siempre es válido/cargable aunque el
    # usuario haya trabajado únicamente por nota, en vez de quedar vacío.
    ma_global = ma if ma.dir_levels is not None else (
        ma.notes[notes_to_save[0]] if notes_to_save else None)
    if ma_global is None:
        raise RuntimeError(
            "Ejecutar compute_directivity() antes de guardar (global o por nota).")

    p = Path(filepath)
    if p.suffix.lower() != '.npz':
        filepath = str(p) + '.npz'

    thetas_numeric = [t for t in ma_global.thetas if t != 'ref']
    theta_indices  = [ma_global.thetas.index(t) for t in thetas_numeric]

    meta = {
        "bands":          bands,
        "ref_azimuth":    ref_azimuth,
        "ref_theta_plot": ref_theta_plot,
        "saved_at":       datetime.now().isoformat(timespec='seconds'),
        "notes":          notes_to_save,
    }

    dir_lev = ma_global.dir_levels[:, theta_indices, :]  # (n_az, n_thetas_num, n_bands)

    kwargs: dict[str, Any] = dict(
        azimuths   = np.array(ma_global.angles, dtype=np.float32),
        thetas     = np.array(thetas_numeric, dtype=np.float32),
        dir_freqs  = ma_global.dir_freqs.astype(np.float32),
        dir_levels = dir_lev.astype(np.float32),
        spl_ref    = ma_global.dir_ref_spl.astype(np.float32),
    )

    spl_ref_az = _spl_ref_per_azimuth(ma_global)
    if spl_ref_az is not None:
        kwargs['spl_ref_per_az'] = spl_ref_az

    for note_name in notes_to_save:
        ma_n  = ma.notes[note_name]
        n_dir = ma_n.dir_levels[:, theta_indices, :]
        kwargs[f'note_{note_name}_dir_levels'] = n_dir.astype(np.float32)
        kwargs[f'note_{note_name}_spl_ref']    = ma_n.dir_ref_spl.astype(np.float32)

        n_spl_ref_az = _spl_ref_per_azimuth(ma_n)
        if n_spl_ref_az is not None:
            kwargs[f'note_{note_name}_spl_ref_per_az'] = n_spl_ref_az

    kwargs['metadata'] = np.array([json.dumps(meta, ensure_ascii=False)])

    np.savez_compressed(filepath, **kwargs)
    size_kb = Path(filepath).stat().st_size / 1024
    print(f"  Guardado: {filepath}  ({size_kb:.0f} KB)")


def drop_bad_thetas(
    filepath_in:  str,
    filepath_out: str,
    bad_thetas:   list[float],
) -> None:
    """
    Elimina filas de thetas corruptos del NPZ (ej. mic roto o mal interpolado).
    La visualización rellenará el hueco con el spline automáticamente.

    Parameters
    ----------
    bad_thetas : ej. [80.0] para eliminar theta=80° (mic_9 roto)
    """
    raw    = np.load(filepath_in, allow_pickle=False)
    thetas = raw['thetas'].astype(np.float64)

    keep = np.ones(len(thetas), dtype=bool)
    for bt in bad_thetas:
        idx = int(np.argmin(np.abs(thetas - bt)))
        if np.abs(thetas[idx] - bt) <= 1.0:
            keep[idx] = False
            print(f"  Eliminando theta={thetas[idx]:.1f}°")
        else:
            print(f"  AVISO: theta={bt}° no encontrado, omitiendo.")

    kwargs = {k: raw[k] for k in raw.files}
    kwargs['thetas']     = thetas[keep].astype(np.float32)
    kwargs['dir_levels'] = raw['dir_levels'][:, keep, :].astype(np.float32)
    for key in raw.files:
        if key.endswith('_dir_levels') and key.startswith('note_'):
            kwargs[key] = raw[key][:, keep, :].astype(np.float32)

    p = str(filepath_out)
    if not p.endswith('.npz'):
        p += '.npz'
    np.savez_compressed(p, **kwargs)
    print(f"  Guardado sin thetas malos: {p}")


def repair_broken_mic(
    filepath_in:  str,
    filepath_out: str,
    bad_thetas:   list[float],
) -> None:
    """
    Sintetiza los thetas de micrófonos rotos usando spline cúbico sobre todos
    los demás thetas medidos (por azimut y banda), y guarda un NPZ corregido.

    Parameters
    ----------
    filepath_in  : NPZ original con datos incorrectos/interpolados manualmente
    filepath_out : NPZ de salida corregido
    bad_thetas   : lista de ángulos theta (en grados) a reconstruir
                   ej. [80.0] para mic_9 roto
    """
    from scipy.interpolate import CubicSpline

    data = load_results(filepath_in)
    thetas     = data['thetas'].astype(np.float64)   # (n_thetas,)
    dir_levels = data['dir_levels'].astype(np.float64)  # (n_az, n_thetas, n_bands)
    n_az, n_thetas, n_bands = dir_levels.shape

    for bad_theta in bad_thetas:
        bad_idx = int(np.argmin(np.abs(thetas - bad_theta)))
        if np.abs(thetas[bad_idx] - bad_theta) > 1.0:
            print(f"  AVISO: theta={bad_theta}° no encontrado en los datos, omitiendo.")
            continue

        good_mask = np.ones(n_thetas, dtype=bool)
        good_mask[bad_idx] = False
        good_thetas = thetas[good_mask]

        if len(good_thetas) < 4:
            print(f"  AVISO: pocos puntos para spline en theta={bad_theta}°, omitiendo.")
            continue

        print(f"  Sintetizando theta={bad_theta}° con spline sobre {good_thetas} °...")
        for ia in range(n_az):
            for ib in range(n_bands):
                vals = dir_levels[ia, good_mask, ib]
                cs   = CubicSpline(good_thetas, vals)
                dir_levels[ia, bad_idx, ib] = float(cs(bad_theta))

    # Preservar el resto del NPZ (notas, metadata, etc.)
    raw = np.load(filepath_in, allow_pickle=False)
    kwargs: dict = {k: raw[k] for k in raw.files}
    kwargs['dir_levels'] = dir_levels.astype(np.float32)

    # También reparar las notas si las hay
    for key in raw.files:
        if key.endswith('_dir_levels') and key.startswith('note_'):
            note_lev = raw[key].astype(np.float64)
            for bad_theta in bad_thetas:
                bad_idx = int(np.argmin(np.abs(thetas - bad_theta)))
                if np.abs(thetas[bad_idx] - bad_theta) > 1.0:
                    continue
                good_mask = np.ones(n_thetas, dtype=bool)
                good_mask[bad_idx] = False
                good_thetas = thetas[good_mask]
                if len(good_thetas) < 4:
                    continue
                for ia in range(n_az):
                    for ib in range(note_lev.shape[2]):
                        vals = note_lev[ia, good_mask, ib]
                        cs   = CubicSpline(good_thetas, vals)
                        note_lev[ia, bad_idx, ib] = float(cs(bad_theta))
            kwargs[key] = note_lev.astype(np.float32)

    p = str(filepath_out)
    if not p.endswith('.npz'):
        p += '.npz'
    np.savez_compressed(p, **kwargs)
    size_kb = Path(p).stat().st_size / 1024
    print(f"  NPZ reparado guardado en: {p}  ({size_kb:.0f} KB)")


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

    if 'spl_ref_per_az' in data:
        result['spl_ref_per_az'] = data['spl_ref_per_az']

    for key in data.files:
        if key.startswith('note_'):
            result[key] = data[key]

    return result
