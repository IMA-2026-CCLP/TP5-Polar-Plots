"""
plot/balloon.py — Genera HTML+Plotly.js para visualizaciones polares.
"""
import json
import numpy as np
from typing import Optional

from core.data_store import freq_label


COLORSCALES = {
    "Viridis":  "Viridis",
    "Plasma":   "Plasma",
    "Inferno":  "Inferno",
    "Hot":      "Hot",
    "RdYlBu":   "RdYlBu_r",
    "Spectral": "Spectral_r",
    "Turbo":    "Turbo",
}

# ── Helpers comunes ───────────────────────────────────────────────────────────

_DARK_BG  = "#1a1d27"
_GRID_COL = "#2e3248"
_TEXT_COL = "#e0e0e0"
_FONT_CSS = "Inter, 'Segoe UI', sans-serif"


def _axes_traces(axis_len: float = 1.15) -> list:
    traces = []
    for vec, label, color in [
        ([axis_len, 0, 0], "X (0°)",    "#ff6b6b"),
        ([0, axis_len, 0], "Y (90°)",   "#51cf66"),
        ([0, 0, axis_len], "Z (cénit)", "#74c0fc"),
    ]:
        traces.append({
            "type": "scatter3d",
            "x": [0, vec[0]], "y": [0, vec[1]], "z": [0, vec[2]],
            "mode": "lines+text",
            "line": {"color": color, "width": 3},
            "text": ["", label],
            "textfont": {"color": color, "size": 11},
            "hoverinfo": "skip", "showlegend": False,
        })
    return traces


def _scene_layout(title: str, uirevision: str = "camera") -> dict:
    return {
        "title": {
            "text": title,
            "font": {"color": _TEXT_COL, "size": 17, "family": _FONT_CSS},
            "x": 0.5, "xanchor": "center",
        },
        "paper_bgcolor": _DARK_BG,
        "plot_bgcolor":  _DARK_BG,
        "margin": {"l": 0, "r": 0, "t": 50, "b": 0},
        "scene": {
            "bgcolor": _DARK_BG,
            "xaxis": {"showgrid": True, "gridcolor": _GRID_COL, "zeroline": False,
                      "showticklabels": False, "showspikes": False},
            "yaxis": {"showgrid": True, "gridcolor": _GRID_COL, "zeroline": False,
                      "showticklabels": False, "showspikes": False},
            "zaxis": {"showgrid": True, "gridcolor": _GRID_COL, "zeroline": False,
                      "showticklabels": False, "showspikes": False},
            "camera": {"eye": {"x": 1.6, "y": 1.2, "z": 0.9}, "up": {"x": 0, "y": 0, "z": 1}},
            "aspectmode": "cube",
        },
        "uirevision": uirevision,
    }


def _colorbar(cs_name: str) -> dict:
    return {
        "colorscale": COLORSCALES.get(cs_name, "Plasma"),
        "colorbar": {
            "title": {"text": "dB", "side": "right"},
            "thickness": 16, "len": 0.6, "x": 0.92,
            "tickfont": {"color": _TEXT_COL, "size": 11},
            "titlefont": {"color": _TEXT_COL},
        },
    }


def _surface_trace(X, Y, Z, surfacecolor, cmin, cmax, cs_name: str,
                   hover=None) -> dict:
    t = {
        "type": "surface",
        "x": X.tolist(), "y": Y.tolist(), "z": Z.tolist(),
        "surfacecolor": surfacecolor.tolist(),
        "cmin": cmin, "cmax": cmax,
        "hovertemplate": ("%{text}<extra></extra>" if hover is not None
                          else "%{surfacecolor:.1f} dB<extra></extra>"),
        "lighting": {"ambient": 0.7, "diffuse": 0.7, "specular": 0.2, "roughness": 0.5},
        "lightposition": {"x": 100, "y": 100, "z": 50},
        "contours": {"z": {"show": False}, "x": {"show": False}, "y": {"show": False}},
        "showscale": True,
    }
    if hover is not None:
        t["text"] = hover
    t.update(_colorbar(cs_name))
    return t


# ── Helpers hemisféricos (idénticos a patron.py) ──────────────────────────────

def _enavg(a: float, b: float) -> float:
    """Promedio de energía en dB."""
    return 10.0 * np.log10((10.0 ** (a / 10.0) + 10.0 ** (b / 10.0)) / 2.0)


def _build_full_ring(rf: np.ndarray, rb: np.ndarray) -> np.ndarray:
    """
    Construye el vector de 2*n-1 pts (φ 0°→360°) desde los vectores front/back.
    rf, rb : (n,) en dB, azimuths 0°→180°.
    Las costuras en φ=0° y φ=180° se promedian en energía (idem patron.py).
    """
    n   = len(rf)
    row = np.empty(2 * n - 1)
    row[0]         = _enavg(float(rf[0]),     float(rb[n - 1]))  # costura φ=0°
    row[1:n - 1]   = rf[1:n - 1]                                  # frente 10°→170°
    row[n - 1]     = _enavg(float(rf[n - 1]), float(rb[0]))      # costura φ=180°
    row[n:2*n - 2] = rb[1:n - 1]                                  # atrás 190°→350°
    row[2*n - 2]   = row[0]                                       # cierra anillo
    return row


def _build_hemisphere_grid(
    lev_2d:     np.ndarray,
    azimuths:   np.ndarray,
    thetas:     np.ndarray,
    interp_deg: Optional[float] = 2.0,
) -> tuple:
    """
    Grilla hemisférica (n_elev × n_phi) en dB, idem plot_polar_3d en patron.py.
    Combina pares front/back theta, promedia en energía en las costuras,
    e interpola con RectBivariateSpline si scipy está disponible.

    Returns: (R_dB, phi_rad, elev_rad, vmin, vmax)
    """
    n_az    = len(azimuths)
    az_step = float(azimuths[1] - azimuths[0]) if n_az > 1 else 10.0
    n_phi   = 2 * n_az - 1

    front_elevs = np.array(sorted(t for t in thetas if 0 <= t <= 90), dtype=float)
    n_elev      = len(front_elevs)

    R_dB = np.zeros((n_elev, n_phi))
    for i_e, e in enumerate(front_elevs):
        i_f = int(np.argmin(np.abs(thetas - e)))
        if abs(e - 90) < 1e-3:   # cénit: promedio energético de todos los azimuths
            col   = lev_2d[:, i_f]
            valid = col[np.isfinite(col)]
            R_dB[i_e, :] = (10 * np.log10(np.mean(10 ** (valid / 10)))
                             if len(valid) else 0.0)
        else:
            e_back = 180.0 - e
            i_b    = int(np.argmin(np.abs(thetas - e_back)))
            R_dB[i_e, :] = _build_full_ring(lev_2d[:, i_f], lev_2d[:, i_b])

    vmin = float(R_dB.min())
    vmax = float(R_dB.max())

    phi_orig  = np.arange(0, 360 + az_step, az_step, dtype=float)
    elev_orig = front_elevs

    # Elevación máxima de la grilla: un paso antes del cénit exacto para evitar
    # la singularidad cos(90°)=0 que colapsa todos los phi a un solo punto.
    max_elev_grid = max(e for e in front_elevs if e < 90.0) if any(e < 90.0 for e in front_elevs) else front_elevs[-1]

    if interp_deg is not None:
        try:
            from scipy.interpolate import RectBivariateSpline
            phi_new  = np.arange(0, 360 + interp_deg, interp_deg, dtype=float)
            phi_new  = phi_new[phi_new <= 360]
            elev_new = np.arange(0, max_elev_grid + interp_deg, interp_deg, dtype=float)
            elev_new = elev_new[elev_new <= max_elev_grid]
            # Recortar R_dB a solo las filas que vamos a interpolar (sin el cénit)
            mask_orig = front_elevs <= max_elev_grid
            spl  = RectBivariateSpline(elev_orig[mask_orig], phi_orig,
                                       R_dB[mask_orig, :], kx=3, ky=3)
            R_dB     = spl(elev_new, phi_new)
            phi_rad  = np.radians(phi_new)
            elev_rad = np.radians(elev_new)
        except Exception:
            phi_rad  = np.radians(phi_orig)
            elev_rad = np.radians(elev_orig[front_elevs <= max_elev_grid])
            R_dB     = R_dB[front_elevs <= max_elev_grid, :]
    else:
        mask_orig = front_elevs <= max_elev_grid
        phi_rad  = np.radians(phi_orig)
        elev_rad = np.radians(elev_orig[mask_orig])
        R_dB     = R_dB[mask_orig, :]

    return R_dB, phi_rad, elev_rad, vmin, vmax


def _wrap_html(traces_json: str, layout_json: str, info_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:100%; height:100%; background:{_DARK_BG}; overflow:hidden; }}
  #plot {{ width:100%; height:100%; }}
  #info-overlay {{
    position:absolute; bottom:14px; left:14px;
    background:rgba(255,255,255,.08); backdrop-filter:blur(6px);
    border:1px solid rgba(255,255,255,.15); border-radius:8px;
    padding:8px 14px; color:#c8ccd8; font-family:{_FONT_CSS};
    font-size:12px; pointer-events:none; line-height:1.7;
  }}
</style>
</head>
<body>
<div id="plot"></div>
<div id="info-overlay">{info_html}</div>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js" charset="utf-8"></script>
<script>
(function() {{
  var traces = {traces_json};
  var layout = {layout_json};
  var cfg = {{ responsive:true, displayModeBar:true,
    modeBarButtonsToRemove:['sendDataToCloud'], displaylogo:false }};
  Plotly.newPlot('plot', traces, layout, cfg);
}})();
</script>
</body>
</html>"""


def _prep_surface(levels, band_index):
    lev_2d = levels[:, :, band_index]
    valid  = np.isfinite(lev_2d)
    gmin   = float(np.nanmin(lev_2d)) if valid.any() else -60.0
    gmax   = float(np.nanmax(lev_2d)) if valid.any() else  0.0
    filled = np.where(valid, lev_2d, gmin)
    return lev_2d, filled, gmin, gmax, valid


def _hover_grid(lev_2d, azimuths, elevations):
    hover = []
    for i, az in enumerate(azimuths):
        row = []
        for j, el in enumerate(elevations):
            v = lev_2d[i, j]
            row.append(
                f"Az: {az:.1f}°  El: {el:.1f}°<br>{v:.1f} dB"
                if np.isfinite(v) else
                f"Az: {az:.1f}°  El: {el:.1f}°<br>Sin dato"
            )
        hover.append(row)
    return hover


def _close_azimuth(arr):
    """Concatena primera fila al final para cerrar el loop azimutal."""
    return np.concatenate([arr, arr[0:1]], axis=0)


# ── 1. Globo 3D (deformado) ───────────────────────────────────────────────────

def build_balloon_html(
    levels:     np.ndarray,
    azimuths:   np.ndarray,
    elevations: np.ndarray,   # todos los thetas numéricos
    band_hz:    float,
    band_index: int,
    colorscale: str = "Plasma",
    normalize:  bool = True,
    min_db:     Optional[float] = None,
    max_db:     Optional[float] = None,
) -> str:
    """
    Globo 3D de directividad. Idem plot_polar_3d en patron.py:
    - Combina front/back theta pares para cubrir 360° en azimuth
    - Promedio energético en las costuras φ=0° y φ=180°
    - Interpolación bicúbica a 2° con RectBivariateSpline
    """
    lev_2d = levels[:, :, band_index]   # (n_az, n_th)

    R_dB, phi_rad, elev_rad, vmin, vmax = _build_hemisphere_grid(
        lev_2d, azimuths, elevations, interp_deg=2.0
    )

    cmin = min_db if min_db is not None else vmin
    cmax = max_db if max_db is not None else vmax
    span = (vmax - vmin) or 1.0

    R_clip = np.clip(R_dB, cmin, cmax)
    if normalize:
        R_r = np.clip((R_dB - vmin) / span, 0.01, 1.0)
    else:
        R_r = R_dB + abs(vmin) + 1.0

    E, P = np.meshgrid(elev_rad, phi_rad, indexing='ij')
    X = R_r * np.cos(E) * np.cos(P)
    Y = R_r * np.cos(E) * np.sin(P)
    Z = R_r * np.sin(E)

    trace  = _surface_trace(X, Y, Z, R_clip, cmin, cmax, colorscale)
    traces = [trace] + _axes_traces()
    layout = _scene_layout(f"Superficie 3D — {freq_label(band_hz)} Hz")

    info = (
        f"<b>Banda:</b> {freq_label(band_hz)} Hz &nbsp;|&nbsp;"
        f"<b>Máx:</b> {vmax:.1f} dB &nbsp;|&nbsp;"
        f"<b>Mín:</b> {vmin:.1f} dB<br>"
        f"<b>Rango dinámico:</b> {vmax - vmin:.1f} dB"
    )
    return _wrap_html(json.dumps(traces), json.dumps(layout), info)


# ── 2. Esfera (radio constante, color = nivel) ────────────────────────────────

def build_sphere_html(
    levels:     np.ndarray,
    azimuths:   np.ndarray,
    elevations: np.ndarray,
    band_hz:    float,
    band_index: int,
    colorscale: str = "Plasma",
    min_db:     Optional[float] = None,
    max_db:     Optional[float] = None,
) -> str:
    """
    Esfera unitaria — idem plot_directivity_sphere en patron.py.
    Radio constante = 1, el nivel se codifica sólo en color.
    """
    lev_2d = levels[:, :, band_index]

    R_dB, phi_rad, elev_rad, vmin, vmax = _build_hemisphere_grid(
        lev_2d, azimuths, elevations, interp_deg=2.0
    )

    cmin = min_db if min_db is not None else vmin
    cmax = max_db if max_db is not None else vmax

    R_clip = np.clip(R_dB, cmin, cmax)

    E, P = np.meshgrid(elev_rad, phi_rad, indexing='ij')
    X = np.cos(E) * np.cos(P)
    Y = np.cos(E) * np.sin(P)
    Z = np.sin(E)

    trace  = _surface_trace(X, Y, Z, R_clip, cmin, cmax, colorscale)
    traces = [trace] + _axes_traces()
    layout = _scene_layout(f"Esfera de Directividad — {freq_label(band_hz)} Hz")

    info = (
        f"<b>Banda:</b> {freq_label(band_hz)} Hz &nbsp;|&nbsp;"
        f"<b>Máx:</b> {vmax:.1f} dB &nbsp;|&nbsp;"
        f"<b>Mín:</b> {vmin:.1f} dB<br>"
        f"<b>Dinámica:</b> {vmax - vmin:.1f} dB"
    )
    return _wrap_html(json.dumps(traces), json.dumps(layout), info)


# ── 3. Polar 2D ───────────────────────────────────────────────────────────────

def build_polar2d_html(
    levels:     np.ndarray,
    azimuths:   np.ndarray,
    elevations: np.ndarray,
    band_hz:    float,
    band_index: int,
    el_index:   Optional[int] = None,
    colorscale: str = "Plasma",
) -> str:
    """
    Gráfico polar 2D.

    Para obtener 360° combina la mitad frontal (azimuths 0–180, theta=el_index)
    con la mitad trasera (azimuths 0–180 desplazados +180°, buscando theta+180°).
    Si no existe la theta opuesta, muestra sólo los 180° disponibles.

    r-axis en dB relativo al máximo (0 dB en frente), rango -30..0 dB.
    """
    lev_2d = levels[:, :, band_index]

    if el_index is None:
        el_index = int(np.argmin(np.abs(elevations)))

    el_deg = float(elevations[el_index])

    # ── Construir traza 360° con promedio energético en costuras (idem patron.py) ─
    r_front  = lev_2d[:, el_index]
    az_front = azimuths.astype(float)
    az_step  = float(az_front[1] - az_front[0]) if len(az_front) > 1 else 10.0

    title_extra  = f"El={el_deg:.0f}°"
    el_back      = 180.0 - el_deg                         # par opuesto
    idx_back_arr = np.where(np.isclose(elevations, el_back, atol=2))[0]

    if len(idx_back_arr) > 0 and abs(el_deg - 90) > 1:
        # Caso normal: par front/back → 37 pts con _enavg en costuras
        idx_back = idx_back_arr[0]
        r_back   = lev_2d[:, idx_back]
        r_full   = _build_full_ring(r_front, r_back)          # (2*n-1) pts
        az_full  = np.arange(0, 360 + az_step, az_step)       # 0°→360°
    elif abs(el_deg - 90) < 1:
        # Cénit: promedio de todos los azimuths
        valid_f = r_front[np.isfinite(r_front)]
        avg = 10 * np.log10(np.mean(10 ** (valid_f / 10))) if len(valid_f) else 0.0
        n_phi   = 2 * len(az_front) - 1
        r_full  = np.full(n_phi, avg)
        az_full = np.arange(0, 360 + az_step, az_step)
    else:
        # Fallback: solo 180° si no hay par
        r_full  = r_front
        az_full = az_front

    # ── Interpolación 1D (idem plot_polar_2d en patron.py) ───────────────────
    try:
        from scipy.interpolate import interp1d
        interp_deg = 1.0
        phi_new    = np.arange(az_full[0], az_full[-1] + interp_deg * 0.01, interp_deg)
        phi_new    = phi_new[phi_new <= az_full[-1]]
        r_full     = interp1d(az_full, r_full, kind='cubic')(phi_new)
        az_full    = phi_new
    except Exception:
        pass   # scipy no disponible → sin interpolación

    # ── Normalizar: 0 dB en az=0° (idem GUI/ui/polar_plot_2d.py) ────────────
    ref_idx = int(np.argmin(np.abs(az_full)))
    ref_val = float(r_full[ref_idx])
    if not np.isfinite(ref_val):
        valid_mask = np.isfinite(r_full)
        dists = np.abs(az_full)
        dists[~valid_mask] = np.inf
        best = int(np.argmin(dists))
        ref_val = float(r_full[best]) if np.isfinite(r_full[best]) else 0.0

    valid = np.isfinite(r_full)
    gmin  = float(np.nanmin(r_full - ref_val)) if valid.any() else -60.0
    gmax  = float(np.nanmax(r_full - ref_val)) if valid.any() else 0.0
    r_rel = np.where(valid, r_full - ref_val, -60.0)

    dyn_range = 30.0   # eje de -30 a 0 dB

    # Cerrar polígono
    az_closed = np.append(az_full, az_full[0])
    r_closed  = np.append(r_rel,   r_rel[0])
    r_abs_cl  = np.append(r_full,  r_full[0])

    # Mapear dB → radio normalizado 0-1 (solo para posicionar el trazo)
    def db_to_r(db): return np.clip(db / dyn_range + 1, 0, 1)

    r_plot = db_to_r(r_closed)

    hover_text = [
        f"Az: {az:.1f}°<br>El: {el_deg:.1f}°<br>{v:.1f} dB SPL  /  {v - ref_val:.1f} dBr (ref 0°)"
        for az, v in zip(az_closed, r_abs_cl)
    ]

    # ── Anillos de referencia ─────────────────────────────────────────────────
    ref_db_rings = [-5, -10, -15, -20, -25, -30]
    ring_traces  = []
    theta_ring   = np.linspace(0, 360, 361)
    for db in ref_db_rings:
        r_ring = db_to_r(np.array([db]))[0]
        ring_traces.append({
            "type": "scatterpolar",
            "r": [r_ring] * 361, "theta": theta_ring.tolist(),
            "mode": "lines",
            "line": {"color": "rgba(255,255,255,0.12)", "width": 1, "dash": "dot"},
            "hovertemplate": f"{db} dBr<extra></extra>",
            "showlegend": False,
        })
        ring_traces.append({
            "type": "scatterpolar",
            "r": [r_ring], "theta": [92],
            "mode": "text",
            "text": [f"{db}"],
            "textfont": {"color": "rgba(200,200,200,0.5)", "size": 9},
            "hoverinfo": "skip", "showlegend": False,
        })

    main_trace = {
        "type": "scatterpolar",
        "r": r_plot.tolist(), "theta": az_closed.tolist(),
        "mode": "lines",
        "fill": "toself",
        "fillcolor": "rgba(99,133,255,0.20)",
        "line": {"color": "#6385ff", "width": 2.5},
        "text": hover_text,
        "hovertemplate": "%{text}<extra></extra>",
        "name": title_extra, "showlegend": False,
    }

    layout = {
        "title": {
            "text": f"Polar 2D — {freq_label(band_hz)} Hz  ({title_extra})",
            "font": {"color": _TEXT_COL, "size": 15, "family": _FONT_CSS},
            "x": 0.5, "xanchor": "center",
        },
        "paper_bgcolor": _DARK_BG,
        "plot_bgcolor":  _DARK_BG,
        "margin": {"l": 40, "r": 40, "t": 60, "b": 40},
        "polar": {
            "bgcolor": _DARK_BG,
            "radialaxis": {
                "visible": True, "range": [0, 1],
                "showticklabels": False, "showgrid": False,
                "linecolor": "rgba(255,255,255,0.1)",
            },
            "angularaxis": {
                "tickfont": {"color": _TEXT_COL, "size": 11},
                "linecolor": "rgba(255,255,255,0.2)",
                "gridcolor": "rgba(255,255,255,0.1)",
                "direction": "clockwise", "rotation": 90,
            },
        },
        "uirevision": "polar2d",
    }

    info = (
        f"<b>Banda:</b> {freq_label(band_hz)} Hz &nbsp;|&nbsp;"
        f"<b>{title_extra}</b> &nbsp;|&nbsp;"
        f"<b>Máx:</b> {gmax:.1f} dB &nbsp;|&nbsp;"
        f"<b>Dinámica:</b> {gmax-gmin:.1f} dB"
    )
    return _wrap_html(json.dumps(ring_traces + [main_trace]), json.dumps(layout), info)


# ── 4. Espectro del micrófono de referencia (barras 1/3 octava) ───────────────

def build_spectrum_html(
    ref_spl_all: np.ndarray,
    bands:       np.ndarray,
    azimuths:    np.ndarray,
    global_mode: bool = True,
) -> str:
    """
    Espectro en barras 1/3 de octava del micrófono de referencia.

    Parameters
    ----------
    ref_spl_all : (n_az, n_bands)  SPL del mic de referencia por azimuth
    bands       : (n_bands,)       frecuencias centrales en Hz
    azimuths    : (n_az,)          azimuths en grados
    global_mode : True → media ± σ;  False → barra por azimuth superpuesta
    """
    # Garantizar orden ascendente de bandas
    sort_idx    = np.argsort(bands)
    bands       = bands[sort_idx]
    ref_spl_all = ref_spl_all[:, sort_idx]
    x_labels    = [freq_label(float(b)) for b in bands]

    n_az = len(azimuths)

    if global_mode:
        mean_vals = np.nanmean(ref_spl_all, axis=0)
        std_vals  = np.nanstd(ref_spl_all,  axis=0, ddof=0)

        bar_trace = {
            "type": "bar",
            "x":    x_labels,
            "y":    [float(v) for v in mean_vals],
            "error_y": {
                "type":      "data",
                "array":     [float(v) for v in std_vals],
                "visible":   True,
                "color":     "rgba(255,200,0,0.85)",
                "thickness": 2,
                "width":     5,
            },
            "name":   "Media",
            "marker": {
                "color": "rgba(88,101,242,0.85)",
                "line":  {"color": "rgba(140,153,255,0.5)", "width": 1},
            },
            "customdata":      [[float(s)] for s in std_vals],
            "hovertemplate":   "%{x}<br><b>%{y:.1f} dB SPL</b><br>σ = %{customdata[0]:.2f} dB<extra></extra>",
        }
        traces = [bar_trace]

        fin = mean_vals[np.isfinite(mean_vals)]
        std_fin = std_vals[np.isfinite(std_vals)]
        y_min = float((fin - std_fin).min()) - 2 if len(fin) else -80
        y_max = float((fin + std_fin).max()) + 2 if len(fin) else 0
        desc  = f"Global — {n_az} azimuths  ·  media ± σ"

    else:
        colors = _az_colors(n_az)
        traces = []
        all_v  = ref_spl_all[np.isfinite(ref_spl_all)]
        y_min  = float(all_v.min()) - 1 if len(all_v) else -80
        y_max  = float(all_v.max()) + 1 if len(all_v) else 0

        for i, az in enumerate(azimuths):
            traces.append({
                "type":   "bar",
                "x":      x_labels,
                "y":      [float(v) if np.isfinite(v) else None
                           for v in ref_spl_all[i]],
                "name":   f"{float(az):.0f}°",
                "marker": {"color": colors[i], "opacity": 0.55},
                "hovertemplate": (
                    f"Az: {float(az):.0f}°<br>%{{x}}<br>"
                    "<b>%{y:.1f} dB SPL</b><extra></extra>"
                ),
            })
        desc = f"0°–180° — {n_az} azimuths superpuestos"

    range_str = f"{freq_label(float(bands[0]))}–{freq_label(float(bands[-1]))} Hz"

    layout = {
        "paper_bgcolor": _DARK_BG,
        "plot_bgcolor":  "#1e2134",
        "margin":  {"l": 65, "r": 20, "t": 45, "b": 70},
        "barmode": "overlay",
        "xaxis": {
            "title":         {"text": "Banda (Hz)", "font": {"color": _TEXT_COL}},
            "tickfont":      {"color": _TEXT_COL, "size": 9},
            "gridcolor":     _GRID_COL,
            "linecolor":     "rgba(255,255,255,0.2)",
            "tickangle":     -45,
            "type":          "category",
            "categoryorder": "array",
            "categoryarray": x_labels,
        },
        "yaxis": {
            "title":    {"text": "dB SPL", "font": {"color": _TEXT_COL}},
            "tickfont": {"color": _TEXT_COL},
            "gridcolor": _GRID_COL,
            "zeroline":  False,
            "range":     [y_min, y_max],
        },
        "legend": {
            "font":    {"color": _TEXT_COL, "size": 9},
            "bgcolor": "rgba(255,255,255,0.04)",
            "x": 1.01, "y": 1,
        },
        "hovermode":  "x unified" if global_mode else "x",
        "uirevision": "spectrum",
    }

    info = (
        f"<b>Mic ref — {desc}</b> &nbsp;|&nbsp;"
        f"<b>Bandas:</b> {range_str}"
    )
    return _wrap_html(json.dumps(traces), json.dumps(layout), info)


def _az_colors(n: int) -> list:
    """Genera n colores tipo arco iris para las trazas de azimuths."""
    import colorsys
    colors = []
    for i in range(n):
        h = i / n
        r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.95)
        colors.append(f"rgb({int(r*255)},{int(g*255)},{int(b*255)})")
    return colors
