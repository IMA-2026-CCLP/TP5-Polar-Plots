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

_DARK_BG        = "#1a1d27"
_GRID_COL       = "#2e3248"
_TEXT_COL       = "#e0e0e0"
_FONT_CSS       = "Inter, 'Segoe UI', sans-serif"
_SPEC_BG        = "#1e2134"
_RING_LINE      = "rgba(255,255,255,0.12)"
_RING_TEXT      = "rgba(200,200,200,0.5)"
_POLAR_AXIS     = "rgba(255,255,255,0.2)"
_POLAR_GRID     = "rgba(255,255,255,0.1)"
_LEGEND_BG      = "rgba(255,255,255,0.04)"
_OVERLAY_BG     = "rgba(255,255,255,.08)"
_OVERLAY_BORDER = "rgba(255,255,255,.15)"


def set_theme(palette: dict) -> None:
    """Actualiza los colores del módulo según la paleta de tema activa."""
    global _DARK_BG, _GRID_COL, _TEXT_COL, _SPEC_BG
    global _RING_LINE, _RING_TEXT, _POLAR_AXIS, _POLAR_GRID
    global _LEGEND_BG, _OVERLAY_BG, _OVERLAY_BORDER
    _DARK_BG        = palette['plot_bg']
    _GRID_COL       = palette['plot_grid']
    _TEXT_COL       = palette['plot_text']
    _SPEC_BG        = palette['spec_plot_bg']
    _RING_LINE      = palette['polar_ring_line']
    _RING_TEXT      = palette['polar_ring_text']
    _POLAR_AXIS     = palette['polar_axis_line']
    _POLAR_GRID     = palette['polar_axis_grid']
    _LEGEND_BG      = palette['legend_bg']
    _OVERLAY_BG     = palette['overlay_bg']
    _OVERLAY_BORDER = palette['overlay_border']


def _axes_traces(axis_len: float = 1.4) -> list:
    traces = []
    for vec, label, color in [
        ([axis_len, 0, 0], "X (0°)",    "#ff6b6b"),
        ([0, axis_len, 0], "Y (90°)",   "#51cf66"),
        ([0, 0, axis_len], "Z (cénit)", "#0d6dff"),
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


def _scene_layout(uirevision: str = "camera", grid_color: Optional[str] = None,
                  grid_width: float = 1) -> dict:
    color = grid_color or _GRID_COL
    axis = {"showgrid": True, "gridcolor": color, "gridwidth": grid_width,
            "zeroline": False, "showticklabels": False, "showspikes": False}
    return {
        "paper_bgcolor": _DARK_BG,
        "plot_bgcolor":  _DARK_BG,
        "margin": {"l": 0, "r": 0, "t": 10, "b": 0},
        "scene": {
            "bgcolor": _DARK_BG,
            "xaxis": dict(axis),
            "yaxis": dict(axis),
            "zaxis": dict(axis),
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

    # Tolerancia para detectar si e_back existe en los datos medidos
    theta_step = float(np.median(np.diff(np.sort(thetas)))) if len(thetas) > 1 else 10.0

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
            if np.abs(thetas[i_b] - e_back) < theta_step * 0.6:
                # Par frontal/trasero real → combinar con promedio energético en costuras
                R_dB[i_e, :] = _build_full_ring(lev_2d[:, i_f], lev_2d[:, i_b])
            else:
                # Solo hemisferio superior: espejo de azimut para mantener continuidad
                R_dB[i_e, :] = _build_full_ring(lev_2d[:, i_f], lev_2d[::-1, i_f])

    # Guardar nivel del cénit (el=90°) antes de excluirlo de la grilla
    zenith_dB: Optional[float] = None
    if any(abs(e - 90.0) < 1e-3 for e in front_elevs):
        i_f90     = int(np.argmin(np.abs(thetas - 90.0)))
        col90     = lev_2d[:, i_f90]
        valid90   = col90[np.isfinite(col90)]
        zenith_dB = float(10 * np.log10(np.mean(10 ** (valid90 / 10)))) if len(valid90) else 0.0

    vmin = float(R_dB.min())
    vmax = float(R_dB.max())

    phi_orig  = np.arange(0, 360 + az_step, az_step, dtype=float)
    elev_orig = front_elevs

    # Elevaciones sin el cénit exacto (singularidad cos=0)
    mask_no_zenith = front_elevs < 89.5
    elev_fit = elev_orig[mask_no_zenith]
    R_fit    = R_dB[mask_no_zenith, :]

    # Si tenemos el cénit medido, agregarlo como restricción al spline
    # (fila constante = zenith_dB) para que el spline converja suavemente,
    # eliminando los "rayos" en el fan cap.
    if zenith_dB is not None and len(elev_fit) > 0 and elev_fit[-1] < 89.0:
        elev_fit = np.append(elev_fit, 89.5)
        R_fit    = np.vstack([R_fit, np.full((1, n_phi), zenith_dB)])

    # Interp hasta 89° (1° antes del cénit) para dejar un fan cap mínimo
    interp_top = min(89.0, float(elev_fit[-1]))

    if interp_deg is not None:
        try:
            from scipy.interpolate import RectBivariateSpline
            phi_new  = np.arange(0, 360 + interp_deg, interp_deg, dtype=float)
            phi_new  = phi_new[phi_new <= 360]
            elev_new = np.arange(0, interp_top + interp_deg * 0.5, interp_deg, dtype=float)
            elev_new = elev_new[elev_new <= interp_top]
            kx = min(3, len(elev_fit) - 1)
            spl  = RectBivariateSpline(elev_fit, phi_orig, R_fit, kx=kx, ky=3)
            R_dB     = spl(elev_new, phi_new)
            phi_rad  = np.radians(phi_new)
            elev_rad = np.radians(elev_new)
        except Exception:
            phi_rad  = np.radians(phi_orig)
            elev_rad = np.radians(elev_fit)
            R_dB     = R_fit
    else:
        phi_rad  = np.radians(phi_orig)
        elev_rad = np.radians(elev_fit)
        R_dB     = R_fit
        R_dB     = R_dB[mask_orig, :]

    return R_dB, phi_rad, elev_rad, vmin, vmax, zenith_dB


def _mirror_grid(X, Y, Z, C):
    """Espeja el hemisferio superior al inferior (reflejo en Z=0).
    Devuelve (X_all, Y_all, Z_all, C_all) con la parte inferior primero."""
    X_lo = np.flipud(X[1:])      # filas 1..n sin el ecuador (evita duplicar el=0°)
    Y_lo = np.flipud(Y[1:])
    Z_lo = -np.flipud(Z[1:])     # Z negado → por debajo del ecuador
    C_lo = np.flipud(C[1:])
    return (np.vstack([X_lo, X]),
            np.vstack([Y_lo, Y]),
            np.vstack([Z_lo, Z]),
            np.vstack([C_lo, C]))


def _cap_mesh_trace(ring_X, ring_Y, ring_Z, apex_x, apex_y, apex_z,
                    ring_colors, apex_color, cmin, cmax, cs_name) -> dict:
    """mesh3d en abanico desde el anillo polar hasta el punto ápice (cénit/nadir)."""
    n = len(ring_X) - 1           # excluir el punto de cierre duplicado
    xs = np.append(ring_X[:n], apex_x)
    ys = np.append(ring_Y[:n], apex_y)
    zs = np.append(ring_Z[:n], apex_z)
    apex_idx = n
    colors   = np.append(ring_colors[:n], apex_color)
    i_tri = list(range(n))
    j_tri = [(k + 1) % n for k in range(n)]
    k_tri = [apex_idx] * n
    return {
        "type": "mesh3d",
        "x": xs.tolist(), "y": ys.tolist(), "z": zs.tolist(),
        "i": i_tri, "j": j_tri, "k": k_tri,
        "intensity": colors.tolist(),
        "intensitymode": "vertex",
        "colorscale": COLORSCALES.get(cs_name, "Plasma"),
        "cmin": float(cmin), "cmax": float(cmax),
        "showscale": False,
        "hoverinfo": "skip",
        "lighting": {"ambient": 0.7, "diffuse": 0.7, "specular": 0.2},
    }


def _wrap_html(traces_json: str, layout_json: str, info_html: str,
               scroll_zoom: bool = False, show_info: bool = True,
               update_only: bool = False) -> str:
    """
    update_only=True devuelve sólo un fragmento de JS (para correr con
    page().runJavaScript()) que actualiza el gráfico YA CARGADO vía
    Plotly.react() en vez de recargar toda la página. Esto preserva cámara,
    zoom y paneo entre cambios de banda/colorscale/escala/etc. — con
    setHtml() se pierden porque cada carga reinicia el contexto de JS.
    Si la página todavía no terminó de cargar por primera vez (window.updatePlot
    no existe aún), el fragmento no hace nada (no-op seguro).
    """
    if update_only:
        info_js = json.dumps(info_html)
        show_js = 'true' if show_info else 'false'
        return (
            f"if (window.updatePlot) {{ "
            f"window.updatePlot({traces_json}, {layout_json}, {info_js}, {show_js}); "
            f"}}"
        )

    sz = 'true' if scroll_zoom else 'false'
    info_display = 'flex' if show_info else 'none'
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
    background:{_OVERLAY_BG}; backdrop-filter:blur(6px);
    border:1px solid {_OVERLAY_BORDER}; border-radius:8px;
    padding:8px 14px; color:{_TEXT_COL}; font-family:{_FONT_CSS};
    font-size:12px; pointer-events:none; line-height:1.6;
    display:{info_display}; flex-direction:column; gap:2px;
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
    modeBarButtonsToRemove:['sendDataToCloud'], displaylogo:false,
    scrollZoom:{sz} }};
  Plotly.newPlot('plot', traces, layout, cfg);

  // Actualiza el gráfico ya cargado sin recrear la página — Plotly.react()
  // conserva cámara/zoom/paneo (vía layout.uirevision) entre actualizaciones.
  window.updatePlot = function(newTraces, newLayout, newInfo, showInfo) {{
    Plotly.react('plot', newTraces, newLayout);
    var el = document.getElementById('info-overlay');
    if (el) {{
      el.innerHTML = newInfo;
      el.style.display = showInfo ? 'flex' : 'none';
    }}
  }};

  // En las escenas 3D (WebGL), Plotly usa el botón derecho para panear la
  // cámara y bloquea el contextmenu nativo del navegador — por eso Qt nunca
  // recibe el evento de click derecho sobre el canvas. Se captura acá y se
  // reenvía a Python por consola (mismo mecanismo que el hover).
  document.addEventListener('contextmenu', function(e) {{
    e.preventDefault();
    console.log('CONTEXTMENU:' + e.clientX + ',' + e.clientY);
  }}, false);
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
    levels:      np.ndarray,
    azimuths:    np.ndarray,
    elevations:  np.ndarray,
    band_hz:     float,
    band_index:  int,
    colorscale:  str = "Plasma",
    normalize:   bool = True,
    min_db:      Optional[float] = None,
    max_db:      Optional[float] = None,
    show_info:   bool = True,
    axis_color:  Optional[str] = None,
    axis_width:  float = 1,
    update_only: bool = False,
) -> str:
    lev_2d = levels[:, :, band_index]

    R_dB, phi_rad, elev_rad, vmin, vmax, zenith_dB = _build_hemisphere_grid(
        lev_2d, azimuths, elevations, interp_deg=2.0
    )

    cmin = min_db if min_db is not None else vmin
    cmax = max_db if max_db is not None else vmax
    span = (vmax - vmin) or 1.0

    R_clip = np.clip(R_dB, cmin, cmax)
    if normalize:
        R_r = np.clip((R_dB - vmin) / span, 0.01, 1.0)
    else:
        R_r = np.clip(R_dB + abs(vmin) + 1.0, 0.01, None)

    E, P = np.meshgrid(elev_rad, phi_rad, indexing='ij')
    X = R_r * np.cos(E) * np.cos(P)
    Y = R_r * np.cos(E) * np.sin(P)
    Z = R_r * np.sin(E)

    # Solo hemisferio superior (sin espejo)
    traces = [_surface_trace(X, Y, Z, R_clip, cmin, cmax, colorscale)]

    # Cap del cénit con mesh3d
    if zenith_dB is not None:
        z_norm  = float(np.clip((zenith_dB - vmin) / span, 0.01, 1.0))
        z_color = float(np.clip(zenith_dB, cmin, cmax))
        traces.append(_cap_mesh_trace(
            X[-1], Y[-1], Z[-1],
            0.0, 0.0, z_norm,
            R_clip[-1], z_color, cmin, cmax, colorscale,
        ))

    traces += _axes_traces()
    layout  = _scene_layout(grid_color=axis_color, grid_width=axis_width)

    zenith_str = f"<br><b>Cénit:</b> {zenith_dB:.1f} dB" if zenith_dB is not None else ""
    info = (
        f"<b>Banda:</b> {freq_label(band_hz)} Hz<br>"
        f"<b>Máx:</b> {vmax:.1f} dB<br>"
        f"<b>Mín:</b> {vmin:.1f} dB{zenith_str}<br>"
        f"<b>Rango dinámico:</b> {vmax - vmin:.1f} dB"
    )
    return _wrap_html(json.dumps(traces), json.dumps(layout), info,
                      show_info=show_info, update_only=update_only)


# ── 2. Esfera (radio constante, color = nivel) ────────────────────────────────

def build_sphere_html(
    levels:      np.ndarray,
    azimuths:    np.ndarray,
    elevations:  np.ndarray,
    band_hz:     float,
    band_index:  int,
    colorscale:  str = "Plasma",
    min_db:      Optional[float] = None,
    max_db:      Optional[float] = None,
    show_info:   bool = True,
    axis_color:  Optional[str] = None,
    axis_width:  float = 1,
    update_only: bool = False,
) -> str:
    """
    Hemisferio superior — radio constante = 1, nivel codificado en color.
    Usa mesh3d triangulado para evitar la singularidad de superficie en el cénit.
    """
    lev_2d = levels[:, :, band_index]

    R_dB, phi_rad, elev_rad, vmin, vmax, zenith_dB = _build_hemisphere_grid(
        lev_2d, azimuths, elevations, interp_deg=2.0
    )

    cmin = min_db if min_db is not None else vmin
    cmax = max_db if max_db is not None else vmax
    R_clip = np.clip(R_dB, cmin, cmax)

    # ── Construir mesh3d triangulado del hemisferio ───────────────────────────
    # phi_rad incluye punto de cierre (0°==360°); usamos n_phi únicos
    n_elev     = len(elev_rad)
    n_phi_full = len(phi_rad)
    n_phi      = n_phi_full - 1   # ángulos únicos (0°..358°)

    # Vértices de la grilla (filas = elevación, cols = azimuth único)
    E, P = np.meshgrid(elev_rad, phi_rad[:n_phi], indexing='ij')
    Xv = (np.cos(E) * np.cos(P)).ravel()
    Yv = (np.cos(E) * np.sin(P)).ravel()
    Zv = np.sin(E).ravel()
    Cv = R_clip[:, :n_phi].ravel()

    # Vértice ápice en el cénit
    if zenith_dB is not None:
        apex_color = float(np.clip(zenith_dB, cmin, cmax))
    else:
        apex_color = float(np.mean(Cv[(n_elev - 1) * n_phi:]))
    apex_idx = len(Xv)
    Xv = np.append(Xv, 0.0)
    Yv = np.append(Yv, 0.0)
    Zv = np.append(Zv, 1.0)
    Cv = np.append(Cv, apex_color)

    i_tri, j_tri, k_tri = [], [], []

    # Quads entre anillos de elevación → 2 triángulos cada uno
    for ie in range(n_elev - 1):
        for ip in range(n_phi):
            ip1 = (ip + 1) % n_phi
            v00 = ie * n_phi + ip
            v01 = ie * n_phi + ip1
            v10 = (ie + 1) * n_phi + ip
            v11 = (ie + 1) * n_phi + ip1
            i_tri += [v00, v00]
            j_tri += [v10, v11]
            k_tri += [v11, v01]

    # Abanico desde el anillo superior hasta el ápice
    for ip in range(n_phi):
        ip1 = (ip + 1) % n_phi
        v0  = (n_elev - 1) * n_phi + ip
        v1  = (n_elev - 1) * n_phi + ip1
        i_tri.append(v0)
        j_tri.append(apex_idx)
        k_tri.append(v1)

    mesh_trace = {
        "type": "mesh3d",
        "x": Xv.tolist(), "y": Yv.tolist(), "z": Zv.tolist(),
        "i": i_tri, "j": j_tri, "k": k_tri,
        "intensity":     Cv.tolist(),
        "intensitymode": "vertex",
        "colorscale":    COLORSCALES.get(colorscale, "Plasma"),
        "cmin": float(cmin), "cmax": float(cmax),
        "showscale": True,
        "colorbar": {
            "title":     {"text": "dB", "side": "right"},
            "thickness": 16, "len": 0.6, "x": 0.92,
            "tickfont":  {"color": _TEXT_COL, "size": 11},
            "titlefont": {"color": _TEXT_COL},
        },
        "lighting":      {"ambient": 0.75, "diffuse": 0.7, "specular": 0.15, "roughness": 0.4},
        "lightposition": {"x": 100, "y": 100, "z": 150},
        "hoverinfo": "skip",
    }

    traces = [mesh_trace] + _axes_traces()
    layout  = _scene_layout(grid_color=axis_color, grid_width=axis_width)
    # Corregir proporción: Z va 0→1 mientras X,Y van -1→1; sin esto Z se estira
    layout["scene"]["aspectmode"]  = "manual"
    layout["scene"]["aspectratio"] = {"x": 1, "y": 1, "z": 0.5}

    zenith_str = f"<br><b>Cénit:</b> {zenith_dB:.1f} dB" if zenith_dB is not None else ""
    info = (
        f"<b>Banda:</b> {freq_label(band_hz)} Hz<br>"
        f"<b>Máx:</b> {vmax:.1f} dB<br>"
        f"<b>Mín:</b> {vmin:.1f} dB{zenith_str}<br>"
        f"<b>Dinámica:</b> {vmax - vmin:.1f} dB"
    )
    return _wrap_html(json.dumps(traces), json.dumps(layout), info,
                      show_info=show_info, update_only=update_only)


# ── 3. Polar 2D ───────────────────────────────────────────────────────────────

_COMPARE_COLORS = [
    "#6385ff", "#ff6b6b", "#51cf66", "#ffd43b",
    "#c084fc", "#22d3ee", "#fb923c", "#f472b6",
]


def _polar_ring_raw(lev_2d, azimuths, elevations, plane, el_index):
    """
    Construye (az_full, r_full, title_extra, hover_label) para UNA banda,
    antes de interpolar/normalizar. Lógica extraída de build_polar2d_html
    para poder reutilizarla por cada banda en el modo de comparación.
    """
    if plane in ("XZ", "YZ"):
        az_deg   = 0.0 if plane == "XZ" else 90.0
        az_index = int(np.argmin(np.abs(azimuths - az_deg)))
        az_real  = float(azimuths[az_index])

        sort_ix = np.argsort(np.mod(elevations.astype(float), 360.0))
        az_full = np.mod(elevations.astype(float), 360.0)[sort_ix]
        r_full  = lev_2d[az_index, :][sort_ix]

        # Evitar duplicados exactos de ángulo (rompen la interpolación cúbica)
        az_full, uniq_ix = np.unique(az_full, return_index=True)
        r_full = r_full[uniq_ix]

        title_extra = f"Plano {plane} (Az={az_real:.0f}°/{(az_real + 180) % 360:.0f}°)"
        hover_label = "θ"
        return az_full, r_full, title_extra, hover_label

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

    hover_label = "Az"
    return az_full, r_full, title_extra, hover_label


def build_polar2d_html(
    levels:        np.ndarray,
    azimuths:      np.ndarray,
    elevations:    np.ndarray,
    band_hz:       float,
    band_index:    int,
    el_index:      Optional[int] = None,
    plane:         str = "XY",
    colorscale:    str = "Plasma",
    min_db:        Optional[float] = None,
    max_db:        Optional[float] = None,
    show_info:      bool = True,
    compare_bands:  Optional[list] = None,
    compare_styles: Optional[dict] = None,
    tick_font_size: float = 11,
    update_only:    bool = False,
) -> str:
    """
    Gráfico polar 2D.

    plane='XY' (horizontal, comportamiento original): fija una elevación (theta)
    y barre el azimuth. Para obtener 360° combina la mitad frontal (azimuths
    0–180, theta=el_index) con la mitad trasera (azimuths 0–180 desplazados
    +180°, buscando theta+180°). Si no existe la theta opuesta, muestra sólo
    los 180° disponibles.

    plane='XZ'/'YZ' (cortes verticales): fija un azimuth (0° o 90°) y barre
    el theta completo. Dado que el arreglo vertical ya recorre 0°→180° pasando
    por el cénit para CUALQUIER azimuth fijo, una sola columna del tensor
    contiene el círculo máximo completo (frente–cénit–atrás) sin necesidad de
    combinar datos de otro azimuth. La simetría de elevación (si el usuario la
    activa en "Simetría") completa el hemisferio inferior no medido.

    compare_bands : lista opcional de (band_index, band_hz) — si se pasa,
    se dibuja un anillo por cada banda superpuesto en el mismo gráfico
    (comparación multibanda), en vez de la banda única (band_index, band_hz).
    Cada anillo se normaliza a 0 dB en su propia dirección de referencia
    (para comparar la FORMA del patrón entre bandas, no el nivel absoluto),
    y la escala radial (autoescala) se ajusta al mínimo/máximo combinado de
    TODAS las bandas mostradas, para que ninguna quede recortada.

    compare_styles : dict opcional {band_index: {'color','width','dash'}} —
    overrides manuales de estilo por banda (ver "Propiedades de bandas…" en
    el menú contextual). Bandas sin entrada usan el color/ancho por defecto.

    r-axis en dB relativo al máximo (0 dB en frente), rango -30..0 dB.
    """
    bands_to_plot = compare_bands if compare_bands else [(band_index, band_hz)]
    multi = len(bands_to_plot) > 1

    rings = []
    for bi, bhz in bands_to_plot:
        lev_2d = levels[:, :, bi]
        az_full, r_full, title_extra, hover_label = _polar_ring_raw(
            lev_2d, azimuths, elevations, plane, el_index
        )

        # ── Interpolación 1D (idem plot_polar_2d en patron.py) ───────────────
        try:
            from scipy.interpolate import interp1d
            interp_deg = 1.0
            phi_new    = np.arange(az_full[0], az_full[-1] + interp_deg * 0.01, interp_deg)
            phi_new    = phi_new[phi_new <= az_full[-1]]
            r_full     = interp1d(az_full, r_full, kind='cubic')(phi_new)
            az_full    = phi_new
        except Exception:
            pass   # scipy no disponible → sin interpolación

        # ── Normalizar: 0 dB en az=0° (idem GUI/ui/polar_plot_2d.py) ─────────
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

        az_closed = np.append(az_full, az_full[0])
        r_closed  = np.append(r_rel,   r_rel[0])
        r_abs_cl  = np.append(r_full,  r_full[0])

        rings.append(dict(
            band_index=bi, band_hz=bhz, az_closed=az_closed, r_closed=r_closed,
            r_abs_cl=r_abs_cl, title_extra=title_extra, hover_label=hover_label,
            gmin=gmin, gmax=gmax,
        ))

    # ── Rango dinámico combinado: min/max de TODAS las bandas mostradas ───────
    step    = 5.0
    all_min = min(r['gmin'] for r in rings)
    all_max = max(r['gmax'] for r in rings)
    r_floor = min_db if min_db is not None else float(np.floor(all_min / step) * step)
    r_ceil  = max_db if max_db is not None else float(np.ceil(all_max / step) * step) if multi else 0.0
    if r_ceil <= r_floor:
        r_ceil = r_floor + step
    dyn_range = r_ceil - r_floor

    def db_to_r(db):
        return np.clip((np.asarray(db, float) - r_floor) / dyn_range, 0, 1)

    # ── Anillos de referencia (cada 5 dB dentro del rango) ───────────────────
    ring_vals    = np.arange(np.ceil(r_floor / step) * step, r_ceil + 0.01, step)
    ring_vals    = ring_vals[(ring_vals > r_floor) & (ring_vals <= r_ceil)]
    ref_db_rings = [float(v) for v in ring_vals]
    ring_traces  = []
    theta_ring   = np.linspace(0, 360, 361)
    for db in ref_db_rings:
        r_ring = float(db_to_r(db))
        ring_traces.append({
            "type": "scatterpolar",
            "r": [r_ring] * 361, "theta": theta_ring.tolist(),
            "mode": "lines",
            "line": {"color": _RING_LINE, "width": 1, "dash": "dot"},
            "hovertemplate": f"{db:g} dBr<extra></extra>",
            "showlegend": False,
        })
        ring_traces.append({
            "type": "scatterpolar",
            "r": [r_ring], "theta": [92],
            "mode": "text",
            "text": [f"{db:g}"],
            "textfont": {"color": _RING_TEXT, "size": max(7, tick_font_size - 2)},
            "hoverinfo": "skip", "showlegend": False,
        })

    # ── Traza principal (una por banda) ───────────────────────────────────────
    styles = compare_styles or {}
    data_traces = []
    for i, ring in enumerate(rings):
        style      = styles.get(ring['band_index'], {})
        line_color = style.get('color', _COMPARE_COLORS[i % len(_COMPARE_COLORS)])
        line_width = style.get('width', 2.5)
        line_dash  = style.get('dash', 'solid')
        r_plot = db_to_r(ring['r_closed'])
        hover_text = [
            f"{ring['hover_label']}: {ang:.1f}°<br>{freq_label(ring['band_hz'])} Hz<br>{v:.1f} dB SPL"
            for ang, v in zip(ring['az_closed'], ring['r_abs_cl'])
        ]
        data_traces.append({
            "type": "scatterpolar",
            "r": r_plot.tolist(), "theta": ring['az_closed'].tolist(),
            "mode": "lines",
            "fill": "toself" if not multi else "none",
            "fillcolor": "rgba(99,133,255,0.20)" if not multi else None,
            "line": {"color": line_color, "width": line_width, "dash": line_dash},
            "text": hover_text,
            "hovertemplate": "%{text}<extra></extra>",
            "name": f"{freq_label(ring['band_hz'])} Hz" if multi else ring['title_extra'],
            "showlegend": multi,
        })

    layout = {
        "paper_bgcolor": _DARK_BG,
        "plot_bgcolor":  _DARK_BG,
        "margin": {"l": 40, "r": 40, "t": 20, "b": 40},
        "polar": {
            "bgcolor": _DARK_BG,
            "radialaxis": {
                "visible": True, "range": [0, 1],
                "showticklabels": False, "showgrid": False,
                "linecolor": _POLAR_GRID,
            },
            "angularaxis": {
                "tickfont": {"color": _TEXT_COL, "size": tick_font_size},
                "linecolor": _POLAR_AXIS,
                "gridcolor": _POLAR_GRID,
                # XY: rotation=90 → 0° arriba (convención brújula).
                # XZ/YZ: rotation=0 → 0° a la derecha, 180° a la izquierda,
                # con 90° (cénit) arriba, dado que theta crece counterclockwise.
                "direction": "counterclockwise",
                "rotation": 90 if plane == "XY" else 0,
            },
        },
        "legend": {
            "font":    {"color": _TEXT_COL, "size": 10},
            "bgcolor": _LEGEND_BG,
            "x": 1.0, "y": 1.0,
        },
        "showlegend": multi,
        "uirevision": "polar2d",
    }

    if multi:
        bands_str = ", ".join(freq_label(r['band_hz']) for r in rings)
        info = (
            f"<b>Comparando {len(rings)} bandas:</b> {bands_str} Hz<br>"
            f"<b>{rings[0]['title_extra']}</b><br>"
            f"<b>Dinámica combinada:</b> {r_ceil - r_floor:.1f} dB"
        )
    else:
        r0 = rings[0]
        info = (
            f"<b>Banda:</b> {freq_label(r0['band_hz'])} Hz<br>"
            f"<b>{r0['title_extra']}</b><br>"
            f"<b>Máx:</b> {r0['gmax']:.1f} dB<br>"
            f"<b>Dinámica:</b> {r0['gmax'] - r0['gmin']:.1f} dB"
        )
    return _wrap_html(json.dumps(ring_traces + data_traces), json.dumps(layout), info,
                      scroll_zoom=True, show_info=show_info, update_only=update_only)


# ── 4. Espectro del micrófono de referencia (barras 1/3 octava) ───────────────

def build_spectrum_html(
    ref_spl_all: np.ndarray,
    bands:       np.ndarray,
    azimuths:    np.ndarray,
    global_mode: bool = True,
    show_info:   bool = True,
    update_only: bool = False,
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
        "plot_bgcolor":  _SPEC_BG,
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
            "bgcolor": _LEGEND_BG,
            "x": 1.01, "y": 1,
        },
        "hovermode":  "x unified" if global_mode else "x",
        "uirevision": "spectrum",
    }

    info = (
        f"<b>Mic ref — {desc}</b><br>"
        f"<b>Bandas:</b> {range_str}"
    )
    return _wrap_html(json.dumps(traces), json.dumps(layout), info,
                      scroll_zoom=True, show_info=show_info, update_only=update_only)


def _az_colors(n: int) -> list:
    """Genera n colores tipo arco iris para las trazas de azimuths."""
    import colorsys
    colors = []
    for i in range(n):
        h = i / n
        r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.95)
        colors.append(f"rgb({int(r*255)},{int(g*255)},{int(b*255)})")
    return colors
