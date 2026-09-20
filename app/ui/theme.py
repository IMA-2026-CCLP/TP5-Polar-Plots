"""ui/theme.py — Paletas clara/oscura y gestor de tema activo.

Fuente única de verdad de color y tipografía para toda la app: QSS
(styles.py), la barra superior nativa (native_ribbon.py) y los widgets
pyqtgraph (f0_editor.py, waveform_editor.py, band_selector.py) leen sus
colores de acá. Los gráficos de Directividad son la única excepción
deliberada — su fondo queda blanco fijo sin importar el tema, ver
tab_directividad.py.
"""
import os as _os

_CHK = _os.path.join(_os.path.dirname(__file__), 'icons', 'check.svg').replace('\\', '/')

_FONT_DISPLAY = "Segoe UI"
_FONT_BODY    = "Segoe UI"
_FONT_MONO    = "Consolas"

LIGHT = dict(
    name="light",
    # UI base — panel gris papel-técnico, superficie blanca
    bg_base="#F0F0F0", bg_panel="#FFFFFF", bg_dark="#E4E4E4",
    text="#1A1A1A", text2="#444444", text_muted="#7A7A7A",
    accent="#2F6DB5", border="#C8C8C8", border2="#A6A6A6",
    accent_ink="#FFFFFF",
    btn_bg="#DCE7F4", btn_border="#9DB8D8", btn_text="#1B4A80", btn_hover="#C9DBEF",
    accent_soft="rgba(47,109,181,.14)", accent_line="rgba(47,109,181,.45)",
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
    bg_base="#2B2B2B", bg_panel="#353535", bg_dark="#222222",
    text="#E6E6E6", text2="#B0B0B0", text_muted="#808080",
    accent="#5B9BD5", border="#454545", border2="#5C5C5C",
    accent_ink="#0E0E0E",
    btn_bg="#34506E", btn_border="#4E7098", btn_text="#DCEBFA", btn_hover="#3F6187",
    accent_soft="rgba(91,155,213,.18)", accent_line="rgba(91,155,213,.5)",
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
