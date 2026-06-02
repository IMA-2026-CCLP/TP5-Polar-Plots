"""
plot/balloon.py — Genera HTML con Plotly.js para el patrón polar 3D tipo balloon
"""
import json
import numpy as np
from typing import Optional
from core.data_store import freq_label


# Paleta de colores personalizable
COLORSCALES = {
    "Viridis":   "Viridis",
    "Plasma":    "Plasma",
    "Inferno":   "Inferno",
    "Hot":       "Hot",
    "RdYlBu":    "RdYlBu_r",
    "Spectral":  "Spectral_r",
    "Turbo":     "Turbo",
}


def build_balloon_html(
    levels: np.ndarray,
    azimuths: np.ndarray,
    elevations: np.ndarray,
    band_hz: float,
    band_index: int,
    colorscale: str = "Plasma",
    normalize: bool = True,
    min_db: Optional[float] = None,
    max_db: Optional[float] = None,
) -> str:
    """
    Construye HTML+JS autónomo con Plotly.js para el balloon interactivo.

    Args:
        levels      : (n_bands, n_az, n_el) dB SPL
        azimuths    : (n_az,) grados, 0–360
        elevations  : (n_el,) grados, 0–180
        band_hz     : frecuencia central de la banda (para el título)
        band_index  : índice en el eje 2 de levels
        colorscale  : nombre del colorscale de Plotly
        normalize   : si True, el radio = lineal normalizado (0–1)
        min_db/max_db: rango de color fijo (None = automático)
    """

    # print(f'Levels: {levels}')
    lev_2d = levels[:, :, band_index]  # (n_az, n_el)

    # Reemplazar NaN por el mínimo para que la malla no tenga huecos
    valid_mask = np.isfinite(lev_2d)
    global_min = float(np.nanmin(lev_2d)) if valid_mask.any() else -60.0
    global_max = float(np.nanmax(lev_2d)) if valid_mask.any() else  0.0

    lev_filled = np.where(valid_mask, lev_2d, global_min)

    # Color range
    cmin = min_db if min_db is not None else global_min
    cmax = max_db if max_db is not None else global_max

    # ── Conversión coordenadas esféricas → cartesianas ────────────────────
    # Convención: az=0→ +X, az=90→ +Y, el=0→ +Z (polo norte), el=180→ -Z
    az_rad  = np.radians(azimuths)    # (n_az,)
    el_rad  = np.radians(elevations)  # (n_el,)

    # Meshgrid (n_az, n_el)
    AZ, EL = np.meshgrid(az_rad, el_rad, indexing='ij')

    # Radio: lineal normalizado 0–1 o en dB relativo
    if normalize:
        r_range = max(global_max - global_min, 1e-6)
        R = (lev_filled - global_min) / r_range
        R = np.clip(R, 0.01, 1.0)   # mínimo 5% para que se vea la forma
    else:
        # radio = dB desplazado para que sea positivo
        offset = abs(global_min) + 1
        R = lev_filled + offset

    X = R * np.cos(EL) * np.cos(AZ)
    Y = R * np.cos(EL) * np.sin(AZ)
    Z = R * np.sin(EL)

    # ── Hover text ────────────────────────────────────────────────────────
    hover = []
    for i, az in enumerate(azimuths):
        row = []
        for j, el in enumerate(elevations):
            db_val = lev_2d[i, j]
            if np.isfinite(db_val):
                row.append(f"Az: {az:.1f}°<br>El: {el:.1f}°<br>{db_val:.1f} dB")
            else:
                row.append(f"Az: {az:.1f}°<br>El: {el:.1f}°<br>Sin dato")
        hover.append(row)
    
    # Close the loop: append first azimuth slice to the end
    X = np.concatenate([X, X[0:1, :]], axis=0)
    Y = np.concatenate([Y, Y[0:1, :]], axis=0)
    Z = np.concatenate([Z, Z[0:1, :]], axis=0)
    lev_2d_closed = np.concatenate([lev_2d, lev_2d[0:1, :]], axis=0)
    
    # Close hover text to match closed data
    hover.append(hover[0])

    # ── Serialización de arrays ───────────────────────────────────────────
    def to_list(arr): return arr.tolist()

    surface_trace = {
        "type": "surface",
        "x": to_list(X),
        "y": to_list(Y),
        "z": to_list(Z),
        "surfacecolor": to_list(lev_2d_closed),
        "colorscale": COLORSCALES.get(colorscale, "Plasma"),
        "cmin": cmin,
        "cmax": cmax,
        "text": hover,
        "hovertemplate": "%{text}<extra></extra>",
        "colorbar": {
            "title": {"text": "dB SPL", "side": "right"},
            "thickness": 16,
            "len": 0.6,
            "x": 0.92,
            "tickfont": {"color": "#e0e0e0", "size": 11},
            "titlefont": {"color": "#e0e0e0"},
        },
        "lighting": {
            "ambient": 0.7,
            "diffuse": 0.7,
            "specular": 0.2,
            "roughness": 0.5,
        },
        "lightposition": {"x": 100, "y": 100, "z": 50},
        "contours": {
            "z": {"show": False},
            "x": {"show": False},
            "y": {"show": False},
        },
        "showscale": True,
    }

    # ── Ejes de referencia (líneas finas) ─────────────────────────────────
    axis_len = 1.15
    axes_traces = []
    for vec, label, color in [
        ([axis_len, 0, 0], "X (0°)", "#ff6b6b"),
        ([0, axis_len, 0], "Y (90°)", "#51cf66"),
        ([0, 0, axis_len], "Z (cénit)", "#74c0fc"),
    ]:
        axes_traces.append({
            "type": "scatter3d",
            "x": [0, vec[0]], "y": [0, vec[1]], "z": [0, vec[2]],
            "mode": "lines+text",
            "line": {"color": color, "width": 3},
            "text": ["", label],
            "textfont": {"color": color, "size": 11},
            "hoverinfo": "skip",
            "showlegend": False,
        })

    all_traces = [surface_trace] + axes_traces

    freq_str = freq_label(band_hz)
    layout = {
        "title": {
            "text": f"Patrón Polar 3D — {freq_str} Hz",
            "font": {"color": "#e0e0e0", "size": 17, "family": "Inter, sans-serif"},
            "x": 0.5,
            "xanchor": "center",
        },
        "paper_bgcolor": "#1a1d27",
        "plot_bgcolor":  "#1a1d27",
        "margin": {"l": 0, "r": 0, "t": 50, "b": 0},
        "scene": {
            "bgcolor": "#1a1d27",
            "xaxis": {
                "title": "", "showgrid": True, "gridcolor": "#2e3248",
                "zeroline": False, "showticklabels": False, "showspikes": False,
            },
            "yaxis": {
                "title": "", "showgrid": True, "gridcolor": "#2e3248",
                "zeroline": False, "showticklabels": False, "showspikes": False,
            },
            "zaxis": {
                "title": "", "showgrid": True, "gridcolor": "#2e3248",
                "zeroline": False, "showticklabels": False, "showspikes": False,
            },
            "camera": {
                "eye": {"x": 1.6, "y": 1.2, "z": 0.9},
                "up":  {"x": 0,   "y": 0,   "z": 1  },
            },
            "aspectmode": "cube",
        },
        "uirevision": "camera",   # ← preserva posición de cámara al redibujar
    }

    # ── HTML autónomo ─────────────────────────────────────────────────────
    traces_json = json.dumps(all_traces, separators=(',', ':'))
    layout_json = json.dumps(layout,     separators=(',', ':'))

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:100%; height:100%; background:#1a1d27; overflow:hidden; }}
  #plot {{ width:100%; height:100%; }}
  #info-overlay {{
    position:absolute; bottom:14px; left:14px;
    background:rgba(255,255,255,.08); backdrop-filter:blur(6px);
    border:1px solid rgba(255,255,255,.15); border-radius:8px;
    padding:8px 14px; color:#c8ccd8; font-family:Inter,sans-serif;
    font-size:12px; pointer-events:none; line-height:1.7;
  }}
</style>
</head>
<body>
<div id="plot"></div>
<div id="info-overlay">
  <b>Banda:</b> {freq_str} Hz &nbsp;|&nbsp;
  <b>Máx:</b> {global_max:.1f} dB &nbsp;|&nbsp;
  <b>Mín:</b> {global_min:.1f} dB<br>
  <b>Rango dinámico:</b> {global_max - global_min:.1f} dB &nbsp;|&nbsp;
  <b>Puntos:</b> {valid_mask.sum()}
</div>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js" charset="utf-8"></script>
<script>
(function() {{
  var traces = {traces_json};
  var layout = {layout_json};
  var cfg = {{
    responsive:       true,
    displayModeBar:   true,
    modeBarButtonsToRemove: ['toImage','sendDataToCloud'],
    displaylogo: false,
  }};
  Plotly.newPlot('plot', traces, layout, cfg).then(function(gd) {{
    gd.on('plotly_hover', function(d) {{
      if (!d || !d.points || !d.points.length) return;
      var pt = d.points[0];
      var msg = JSON.stringify({{
        az:  pt.customdata ? pt.customdata[0] : null,
        el:  pt.customdata ? pt.customdata[1] : null,
        db:  pt.surfacecolor !== undefined ? pt.surfacecolor : null,
        x: pt.x, y: pt.y, z: pt.z,
        text: pt.text || ''
      }});
      console.log('HOVER:' + msg);
    }});
  }});
}})();
</script>
</body>
</html>"""
    return html
