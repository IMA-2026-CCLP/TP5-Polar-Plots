"""Archivo de grilla procesada (.gcclp): guarda la grilla de 10° ya corregida y nivelada, sin la
interpolación ni el suavizado (esos se vuelven a elegir al abrir). Formato npz + metadatos en JSON."""
import json
import numpy as np


def _jsonable(o):
    """Convierte tipos de numpy y similares a JSON (estilos de las vistas)."""
    if hasattr(o, 'tolist'):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)

EXT = ".gcclp"


def save_grid(path, levels, azimuths, thetas, freqs, unit, meta=None, ref_raw=None, ref_eq=None):
    extra = {}
    if ref_raw is not None and ref_eq is not None:
        extra = dict(ref_raw=np.asarray(ref_raw, dtype=np.float32), ref_eq=np.asarray(ref_eq, dtype=np.float32))
    with open(path, 'wb') as f:      # así no se le agrega '.npz' al nombre
     np.savez_compressed(
        f,
        **extra,
        levels=np.asarray(levels, dtype=np.float32),
        azimuths=np.asarray(azimuths, dtype=np.float32),
        thetas=np.asarray(thetas, dtype=np.float32),
        freqs=np.asarray([np.nan if f is None else float(f) for f in freqs], dtype=np.float32),
        unit=np.array(str(unit)),
        meta=np.array(json.dumps(meta or {}, default=_jsonable)),
    )


def load_grid(path):
    with np.load(path, allow_pickle=False) as d:
        return {
            "levels":    d["levels"].astype(np.float32),
            "azimuths":  d["azimuths"].astype(np.float32),
            "thetas":    d["thetas"].astype(np.float32),
            "freqs":     d["freqs"].astype(np.float32),
            "unit":      str(d["unit"]),
            "meta":      json.loads(str(d["meta"])),
            "ref_raw":   d["ref_raw"].astype(np.float32) if "ref_raw" in d.files else None,
            "ref_eq":    d["ref_eq"].astype(np.float32) if "ref_eq" in d.files else None,
        }
