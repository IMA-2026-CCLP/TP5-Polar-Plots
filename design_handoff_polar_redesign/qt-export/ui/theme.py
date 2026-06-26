"""ui/theme.py — Paletas oscura/clara y gestor de tema activo.

Rediseño "Polar Pattern Analyzer":
  · DARK  = Graphite  (oscuro frío, acento cian)
  · LIGHT = Daylight  (claro neutro, acento índigo)

Reemplazo directo del theme.py original: mismas claves + algunas nuevas
(accent_ink, accent_hover, ok, warn, err) usadas por el styles.py nuevo.
"""
import os as _os

_CHK = _os.path.join(_os.path.dirname(__file__), 'icons', 'check.svg').replace('\\', '/')

DARK = dict(
    name="dark",
    # ── UI base ───────────────────────────────────────────────
    bg_base="#15171c", bg_panel="#1c1f26", bg_dark="#0f1115",
    text="#e8eaef", text2="#969ba6", text_muted="#686d77",
    accent="#2dd4bf", accent_ink="#06302b", accent_hover="#3ee3ce",
    border="#2a2e37", border2="#363b46",
    # ── Ribbon ────────────────────────────────────────────────
    rb_tabs="#1b1e24", rb_panel="#1d2027",
    rb_hint="#969ba6", rb_icon="#aeb4bf",
    rb_sep="#2a2e37", rb_btn_bg="#0f1115", rb_btn_bor="#363b46",
    rb_grp_lbl="#686d77", rb_disabled="#3a3f4a",
    # ── Semánticos ────────────────────────────────────────────
    ok="#46d39a", warn="#e7b15a", err="#ef6b6b",
    # ── Plot ──────────────────────────────────────────────────
    plot_bg="#0f1116", plot_grid="#23262f", plot_text="#c8ccd4",
    spec_plot_bg="#0f1116",
    # ── Overlays / polar ──────────────────────────────────────
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
    # ── UI base ───────────────────────────────────────────────
    bg_base="#eef0f4", bg_panel="#ffffff", bg_dark="#f3f5f8",
    text="#1b1e26", text2="#545a66", text_muted="#8a909c",
    accent="#3b54d6", accent_ink="#ffffff", accent_hover="#4a62e0",
    border="#dfe3ea", border2="#cad0db",
    # ── Ribbon ────────────────────────────────────────────────
    rb_tabs="#ffffff", rb_panel="#ffffff",
    rb_hint="#545a66", rb_icon="#545a66",
    rb_sep="#dfe3ea", rb_btn_bg="#f3f5f8", rb_btn_bor="#cad0db",
    rb_grp_lbl="#8a909c", rb_disabled="#b8bcc8",
    # ── Semánticos ────────────────────────────────────────────
    ok="#1f9d63", warn="#c98a2b", err="#d65151",
    # ── Plot ──────────────────────────────────────────────────
    plot_bg="#f7f8fb", plot_grid="#e7eaf0", plot_text="#1b1e26",
    spec_plot_bg="#f7f8fb",
    # ── Overlays / polar ──────────────────────────────────────
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
