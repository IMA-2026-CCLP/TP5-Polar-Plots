"""
core/session.py — Guardar y cargar sesiones .cclp.

Un .cclp es un NPZ con el MISMO contenido que la directividad .npz de core/data_store.py
(azimuts/thetas/bandas/niveles, notas con su directividad y la configuración de los 4 gráficos)
más el estado COMPLETO de los controles de la interfaz (no sólo los de Directividad). No incluye
el audio: sólo lo necesario para redibujar los gráficos ya calculados. Por eso, al reabrir una
sesión no se puede reprocesar audio (alinear, calibrar, re-detectar notas, recalcular con otras
bandas) — para eso hay que volver a cargar los WAV (Archivo ▸ Cargar audio…). Es el mismo
comportamiento que ya tenía cargar un .npz de directividad "sin audios".

Un .cclp NO reemplaza a "Guardar/Cargar audio procesado (.npz)" (ver ui/file_loader.py), que sigue
guardando el tensor crudo para resumir el preprocesamiento sin los WAV originales.
"""
from core.data_store import save_results, load_results


def save_cclp(path: str, ma, ui_state: dict | None = None, **kwargs) -> None:
    """Guarda una sesión .cclp (ver docstring del módulo). kwargs: bands/ref_azimuth/ref_theta_plot/view,
    igual que save_results()."""
    from pathlib import Path
    path = str(Path(path).with_suffix('.cclp'))
    view = dict(kwargs.pop('view', None) or {})
    view['session_ui'] = ui_state or {}
    save_results(filepath=path, ma=ma, view=view, **kwargs)


def load_cclp(path: str) -> dict:
    """Carga una sesión .cclp. Ver core/data_store.py:load_results() para la forma del dict
    devuelto; metadata['view']['session_ui'] tiene el estado completo de la interfaz guardado."""
    return load_results(path)
