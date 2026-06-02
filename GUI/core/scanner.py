"""
core/scanner.py — Folder scanning and filename template matching
"""
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Set


AUDIO_EXTENSIONS: Set[str] = {'.wav', '.flac', '.aif', '.aiff', '.mp3', '.ogg', '.w64'}


@dataclass
class AudioFile:
    path: str
    azimuth: float
    elevation: float
    filename: str


# ─── Template → Regex ────────────────────────────────────────────────────────

def template_to_regex(template: str) -> re.Pattern:
    """
    Convierte un template de usuario a regex compilada.

    Placeholders soportados:
        {H}         → captura ángulo horizontal (azimut)
        {H:03d}     → igual, el formato es solo decorativo
        {H:.1f}     → igual
        {V}         → captura ángulo vertical (elevación)
        {V:03d}     → igual

    Ejemplos:
        "audio_{H:03d}_{V:03d}.wav"   →  audio_045_030.wav
        "meas_az{H}_el{V}.flac"       →  meas_az45_el30.flac
        "{H}-{V}.wav"                 →  45-30.wav
    """
    NUMBER_PAT = r'(?P<{name}>-?\d+\.?\d*)'

    parts = re.split(r'(\{[HhVv](?::[^}]*)?\})', template)
    pattern_str = ''
    h_seen = v_seen = False

    for part in parts:
        if re.match(r'^\{[Hh](?::[^}]*)?\}$', part):
            if h_seen:
                raise ValueError("El placeholder {H} aparece más de una vez.")
            pattern_str += NUMBER_PAT.format(name='H')
            h_seen = True
        elif re.match(r'^\{[Vv](?::[^}]*)?\}$', part):
            if v_seen:
                raise ValueError("El placeholder {V} aparece más de una vez.")
            pattern_str += NUMBER_PAT.format(name='V')
            v_seen = True
        else:
            pattern_str += re.escape(part)

    if not h_seen:
        raise ValueError("El template no contiene {H} (ángulo horizontal).")
    if not v_seen:
        raise ValueError("El template no contiene {V} (ángulo vertical).")

    return re.compile('^' + pattern_str + '$', re.IGNORECASE)


def template_preview(template: str, h_example: float = 45.0, v_example: float = 30.0) -> str:
    """Genera un nombre de ejemplo a partir del template."""
    try:
        # Try formatting with the user template
        return template.format(H=int(h_example), V=int(v_example))
    except (ValueError, KeyError):
        pass
    try:
        return template.format(H=h_example, V=v_example)
    except Exception:
        # If template has format specs like :03d, use format_map trick
        import string
        class SafeFormat(dict):
            def __missing__(self, key):
                return '{' + key + '}'
        # Replace {H:...} → formatted number
        result = re.sub(
            r'\{H(?::([^}]*))?\}',
            lambda m: f'{h_example:{m.group(1) or ""}}' if m.group(1) else str(h_example),
            template
        )
        result = re.sub(
            r'\{V(?::([^}]*))?\}',
            lambda m: f'{v_example:{m.group(1) or ""}}' if m.group(1) else str(v_example),
            result
        )
        return result


# ─── Folder scanning ─────────────────────────────────────────────────────────

def scan_folder(
    folder: str,
    template: str,
    extensions: Optional[Set[str]] = None,
) -> Tuple[List[AudioFile], List[str], Optional[str]]:
    """
    Escanea una carpeta y matchea archivos contra el template.

    Returns:
        (matched_files, unmatched_filenames, error_message)
        error_message is None if no critical error.
    """
    ext_set = extensions or AUDIO_EXTENSIONS

    try:
        pattern = template_to_regex(template)
    except (ValueError, re.error) as e:
        return [], [], str(e)

    p = Path(folder)
    if not p.is_dir():
        return [], [], f"Carpeta no encontrada: {folder}"

    matched: List[AudioFile] = []
    unmatched: List[str] = []

    for fpath in sorted(p.iterdir()):
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() not in ext_set:
            continue

        m = pattern.match(fpath.name)
        if m:
            try:
                az = float(m.group('H'))
                el = float(m.group('V'))
                matched.append(AudioFile(
                    path=str(fpath),
                    azimuth=az,
                    elevation=el,
                    filename=fpath.name,
                ))
            except (IndexError, ValueError):
                unmatched.append(fpath.name)
        else:
            unmatched.append(fpath.name)

    return matched, unmatched, None


def get_grid_info(files: List[AudioFile]) -> Dict:
    """Analiza la grilla de ángulos en los archivos detectados."""
    if not files:
        return {}

    azimuths = sorted(set(round(f.azimuth, 6) for f in files))
    elevations = sorted(set(round(f.elevation, 6) for f in files))

    def uniform_step(vals: list) -> Optional[float]:
        if len(vals) < 2:
            return None
        diffs = [round(vals[i + 1] - vals[i], 6) for i in range(len(vals) - 1)]
        return diffs[0] if len(set(diffs)) == 1 else None

    return {
        'n_matched': len(files),
        'azimuths': azimuths,
        'elevations': elevations,
        'n_az': len(azimuths),
        'n_el': len(elevations),
        'h_range': (min(azimuths), max(azimuths)),
        'v_range': (min(elevations), max(elevations)),
        'h_step': uniform_step(azimuths),
        'v_step': uniform_step(elevations),
        'complete': len(files) == len(azimuths) * len(elevations),
    }
