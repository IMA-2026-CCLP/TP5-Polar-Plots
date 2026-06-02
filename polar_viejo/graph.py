# -*- coding: utf-8 -*-
"""
polar/graph.py

Funciones de visualización.

Uso desde un notebook:
    from polar.graph import takes

    # Todas las tomas de un mic (eje azimuth)
    takes(polar_data[:, 10, :], modo='angulos', sr=SR, titulo="Mic 10")

    # Todos los mics de una toma
    takes(polar_data[0, :, :], modo='mics', sr=SR, titulo="Toma 0°")
"""

import numpy as np
import plotly.graph_objects as go


def takes(datos, modo, mics=None, angulos=None, titulo="Título", sr=44100, n_puntos=5000, width=1240, height=520):
    """
    Grafica tomas de audio.

    Parámetros
    ----------
    datos   : np.ndarray 2D  (n_filas x n_samples)
    modo    : str            'angulos' o 'mics'
                              'angulos' → cada fila es una toma (eje azimuth)
                              'mics'    → cada fila es un micrófono
    mics    : list           necesario si modo='mics'   ['ref', 1, 2, ..., 19]
    angulos : list           necesario si modo='angulos' [0, 10, ..., 180]
    titulo  : str            título del gráfico
    sr      : int            sample rate (Hz)
    n_puntos: int            cantidad de puntos para el downsampling visual
    width   : int            ancho del gráfico en px
    height  : int            alto del gráfico en px
    """

    # -- Armar etiquetas según modo ----------------------------------------
    if modo == 'angulos':
        if angulos is None:
            # Si no se pasan, los inferimos del número de filas
            angulos = list(range(0, datos.shape[0] * 10, 10))
        etiquetas = [f"{ang}°" for ang in angulos]
        leyenda   = "Ángulo"

    elif modo == 'mics':
        if mics is None:
            # Si no se pasan, numeramos desde 1
            mics = list(range(1, datos.shape[0] + 1))
        etiquetas = [f"mic_{m}" for m in mics]
        leyenda   = "Micrófono"

    else:
        raise ValueError(f"modo debe ser 'angulos' o 'mics', recibí: '{modo}'")

    # -- Downsampling visual (max en ventanas) ------------------------------
    n_samples      = datos.shape[1]
    factor         = max(1, n_samples // n_puntos)
    largo_ajustado = factor * (n_samples // factor)
    t              = np.arange(largo_ajustado) / sr
    t_ds           = t.reshape(-1, factor).mean(axis=1)

    # -- Graficar -----------------------------------------------------------
    fig = go.Figure()

    for i, etiqueta in enumerate(etiquetas):
        signal_ds = np.abs(datos[i, :largo_ajustado]).reshape(-1, factor).max(axis=1)
        fig.add_trace(go.Scatter(
            x=t_ds,
            y=signal_ds,
            name=etiqueta,
            line=dict(width=1),
            opacity=0.8
        ))

    fig.update_layout(
        title=titulo,
        xaxis_title="Tiempo (s)",
        yaxis_title="Amplitud",
        legend_title=leyenda,
        legend=dict(font=dict(size=10)),
        width=width,
        height=height
    )

    fig.show()