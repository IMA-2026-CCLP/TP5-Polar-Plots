"""ui/theme.py — Paletas oscura/clara y gestor de tema activo."""
import os as _os

_CHK = _os.path.join(_os.path.dirname(__file__), 'icons', 'check.svg').replace('\\', '/')

DARK = dict(
    name="dark",
    # UI base
    bg_base="#13151f", bg_panel="#1d2035", bg_dark="#0f1119",
    text="#dde3f4", text2="#9aa6cc", text_muted="#6b7898",
    accent="#6070d0", border="#252840", border2="#353a58",
    # Ribbon
    rb_tabs="#0d0f18", rb_panel="#181b2c",
    rb_hint="#8a96be", rb_icon="#9aa6cc",
    rb_sep="#353a58", rb_btn_bg="#1e2238", rb_btn_bor="#3a3f60",
    rb_grp_lbl="#606880", rb_disabled="#2e3248",
    # Plot
    plot_bg="#1a1d27", plot_grid="#2e3248", plot_text="#e0e0e0",
    spec_plot_bg="#1e2134",
    # Overlays / polar
    polar_ring_line="rgba(255,255,255,0.12)",
    polar_ring_text="rgba(200,200,200,0.5)",
    polar_axis_line="rgba(255,255,255,0.2)",
    polar_axis_grid="rgba(255,255,255,0.1)",
    legend_bg="rgba(255,255,255,0.04)",
    overlay_bg="rgba(255,255,255,.08)",
    overlay_border="rgba(255,255,255,.15)",
    chk_icon=_CHK,
)

LIGHT = dict(
    name="light",
    # UI base
    bg_base="#f4f5fa", bg_panel="#ffffff", bg_dark="#eaecf4",
    text="#1e2035", text2="#4a5070", text_muted="#6a7090",
    accent="#5060c0", border="#d0d4e8", border2="#b8bcd0",
    # Ribbon
    rb_tabs="#dddfe8", rb_panel="#e8eaf2",
    rb_hint="#5a6080", rb_icon="#5a6080",
    rb_sep="#b8bcd0", rb_btn_bg="#d0d2de", rb_btn_bor="#b0b4c8",
    rb_grp_lbl="#7a80a0", rb_disabled="#b0b4c8",
    # Plot
    plot_bg="#f8f8fc", plot_grid="#d8daea", plot_text="#1e2035",
    spec_plot_bg="#f0f2fa",
    # Overlays / polar
    polar_ring_line="rgba(0,0,0,0.15)",
    polar_ring_text="rgba(80,80,80,0.7)",
    polar_axis_line="rgba(0,0,0,0.2)",
    polar_axis_grid="rgba(0,0,0,0.1)",
    legend_bg="rgba(0,0,0,0.04)",
    overlay_bg="rgba(0,0,0,.08)",
    overlay_border="rgba(0,0,0,.12)",
    chk_icon=_CHK,
)

_current = DARK


def current() -> dict:
    return _current


def toggle() -> dict:
    global _current
    _current = LIGHT if _current is DARK else DARK
    return _current


def is_dark() -> bool:
    return _current is DARK
