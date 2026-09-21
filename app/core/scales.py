"""
core/scales.py — Biblioteca de escalas musicales para la detección de notas.

Escala = {nombre de nota: frecuencia en Hz} (ej. {"Fa4": 349.23, "Sol4": 392.0, ...}).

- Escalas integradas, generadas en temperamento igual (La4 = 440 Hz) y clasificadas por categoría.
- Base propia del usuario: JSON en el perfil del usuario (%APPDATA%/PolarPatternCCLP/scales.json),
  con sus propias categorías. Se puede importar/exportar para compartirla.

Los nombres de escala son únicos en toda la biblioteca (integradas + propias).
"""
import json
import os
from pathlib import Path

USER_CATEGORY = "Mis escalas"
DEFAULT_SCALE = "Fa mayor"

_SHARP = ["Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]
_FLAT  = ["Do", "Reb", "Re", "Mib", "Mi", "Fa", "Solb", "Sol", "Lab", "La", "Sib", "Si"]
_FLAT_KEYS = {5, 10, 3, 8, 1, 6}          # Fa, Sib, Mib, Lab, Reb, Solb: se escriben con bemoles


def _note(midi: int, flat: bool) -> tuple[str, float]:
    names = _FLAT if flat else _SHARP
    return f"{names[midi % 12]}{midi // 12 - 1}", round(440.0 * 2 ** ((midi - 69) / 12), 2)


def _scale(tonic_pc: int, intervals: list[int]) -> dict:
    flat = tonic_pc in _FLAT_KEYS
    root = 60 + tonic_pc                    # octava 4
    return dict(_note(root + i, flat) for i in intervals)


def _tonic_name(pc: int) -> str:
    return (_FLAT if pc in _FLAT_KEYS else _SHARP)[pc]


_MAJOR = [0, 2, 4, 5, 7, 9, 11, 12]
_MINOR = [0, 2, 3, 5, 7, 8, 10, 12]
_HARM  = [0, 2, 3, 5, 7, 8, 11, 12]
_PENTA = [0, 2, 4, 7, 9, 12]


def builtin() -> dict:
    """{categoría: {nombre: escala}} — sólo lectura."""
    order = list(range(12))               # Do, Reb, Re, ... Si
    cats = {
        "Mayores":            {f"{_tonic_name(pc)} mayor":           _scale(pc, _MAJOR) for pc in order},
        "Menores naturales":  {f"{_tonic_name(pc)} menor":           _scale(pc, _MINOR) for pc in order},
        "Menores armónicas":  {f"{_tonic_name(pc)} menor armónica":  _scale(pc, _HARM) for pc in order},
        "Pentatónicas":       {f"{_tonic_name(pc)} pentatónica":     _scale(pc, _PENTA) for pc in order},
        "Cromática":          {"Cromática (Do4–Do5)": _scale(0, list(range(13)))},
    }
    return cats


# ── base del usuario ──────────────────────────────────────────────────────────

def user_db_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "PolarPatternCCLP" / "scales.json"


def load_user(path: Path | None = None) -> dict:
    """{categoría: {nombre: escala}} de la base propia ({} si no existe o está dañada)."""
    p = path or user_db_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cats = data.get("categories", {})
        return {c: {n: {k: float(v) for k, v in sc.items()} for n, sc in d.items()} for c, d in cats.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def save_user(cats: dict, path: Path | None = None) -> None:
    p = path or user_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "categories": cats}, ensure_ascii=False, indent=1), encoding="utf-8")


# ── biblioteca combinada ──────────────────────────────────────────────────────

def library(path: Path | None = None) -> dict:
    """{categoría: {nombre: escala}}: integradas primero, luego las del usuario."""
    lib = builtin()
    for cat, d in load_user(path).items():
        lib.setdefault(cat, {}).update(d)
    return lib


def find(name: str, path: Path | None = None):
    """(categoría, escala) de la escala con ese nombre, o (None, None)."""
    for cat, d in library(path).items():
        if name in d:
            return cat, dict(d[name])
    return None, None


def is_builtin(name: str) -> bool:
    return any(name in d for d in builtin().values())


def default_scale() -> dict:
    return find(DEFAULT_SCALE)[1]


def merge_into_user(incoming: dict, path: Path | None = None) -> int:
    """Suma escalas importadas a la base propia (ignora nombres que chocan con las integradas). Devuelve cuántas."""
    user = load_user(path)
    n = 0
    for cat, d in incoming.items():
        for name, sc in d.items():
            if is_builtin(name) or not sc:
                continue
            user.setdefault(cat or USER_CATEGORY, {})[name] = {k: float(v) for k, v in sc.items()}
            n += 1
    save_user(user, path)
    return n
