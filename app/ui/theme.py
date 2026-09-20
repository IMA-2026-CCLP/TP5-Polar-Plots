"""ui/theme.py — Paletas clara/oscura y gestor de tema activo.

Fuente única de verdad de color y tipografía para toda la app: QSS
(styles.py), el ribbon HTML (via bridge.py → shell.html) y los widgets
pyqtgraph (f0_editor.py, waveform_editor.py, band_selector.py) leen sus
colores de acá. Los gráficos de Directividad son la única excepción
deliberada — su fondo queda blanco fijo sin importar el tema, ver
tab_directividad.py.
"""
import os as _os

_CHK = _os.path.join(_os.path.dirname(__file__), 'icons', 'check.svg').replace('\\', '/')

_FONT_DISPLAY = "IBM Plex Sans Condensed"
_FONT_BODY    = "IBM Plex Sans"
_FONT_MONO    = "IBM Plex Mono"

LIGHT = dict(
    name="light",
    # UI base — panel gris papel-técnico, superficie blanca
    bg_base="#F5F6F7", bg_panel="#FFFFFF", bg_dark="#EDEFF2",
    text="#1B1F24", text2="#5B6570", text_muted="#8A93A0",
    accent="#146B64", border="#D8DCE0", border2="#C3C9CE",
    accent_ink="#FFFFFF",
    accent_soft="rgba(20,107,100,.10)", accent_line="rgba(20,107,100,.35)",
    ok="#1A9E5C",
    # Ribbon
    rb_tabs="#FFFFFF", rb_panel="#F0F1F4",
    rb_hint="#5B6570", rb_icon="#5B6570",
    rb_sep="#D8DCE0", rb_btn_bg="#EDEFF2", rb_btn_bor="#D8DCE0",
    rb_grp_lbl="#8A93A0", rb_disabled="#C3C9CE",
    # Plot chrome (los 4 gráficos de Directividad ignoran esto, ver arriba)
    plot_bg="#FFFFFF", plot_grid="#D8DCE0", plot_text="#1B1F24",
    spec_plot_bg="#FFFFFF",
    # Overlays / polar
    polar_ring_line="rgba(27,31,36,0.15)",
    polar_ring_text="rgba(91,101,112,0.7)",
    polar_axis_line="rgba(27,31,36,0.2)",
    polar_axis_grid="rgba(27,31,36,0.1)",
    legend_bg="rgba(27,31,36,0.04)",
    overlay_bg="rgba(255,255,255,.9)",
    overlay_border="rgba(27,31,36,.15)",
    chk_icon=_CHK,
    font_display=_FONT_DISPLAY, font_body=_FONT_BODY, font_mono=_FONT_MONO,
)

DARK = dict(
    name="dark",
    # UI base
    bg_base="#15181B", bg_panel="#1D2124", bg_dark="#101214",
    text="#EDEFF1", text2="#9AA4AA", text_muted="#6B7378",
    accent="#3FCDB8", border="#2C3236", border2="#3A4146",
    accent_ink="#0D1210",
    accent_soft="rgba(63,205,184,.14)", accent_line="rgba(63,205,184,.4)",
    ok="#46D39A",
    # Ribbon
    rb_tabs="#101214", rb_panel="#191D20",
    rb_hint="#9AA4AA", rb_icon="#9AA4AA",
    rb_sep="#3A4146", rb_btn_bg="#22262A", rb_btn_bor="#3A4146",
    rb_grp_lbl="#6B7378", rb_disabled="#2C3236",
    # Plot chrome (los 4 gráficos de Directividad ignoran esto, ver arriba)
    plot_bg="#1D2124", plot_grid="#2C3236", plot_text="#EDEFF1",
    spec_plot_bg="#1D2124",
    # Overlays / polar
    polar_ring_line="rgba(255,255,255,0.12)",
    polar_ring_text="rgba(200,200,200,0.5)",
    polar_axis_line="rgba(255,255,255,0.2)",
    polar_axis_grid="rgba(255,255,255,0.1)",
    legend_bg="rgba(255,255,255,0.04)",
    overlay_bg="rgba(29,33,36,.9)",
    overlay_border="rgba(255,255,255,.15)",
    chk_icon=_CHK,
    font_display=_FONT_DISPLAY, font_body=_FONT_BODY, font_mono=_FONT_MONO,
)

_current = LIGHT


def current() -> dict:
    return _current


def toggle() -> dict:
    global _current
    _current = DARK if _current is LIGHT else LIGHT
    return _current


def is_dark() -> bool:
    return _current is DARK
