# -*- coding: utf-8 -*-
"""
polar/patron.py

Cálculo y visualización del patrón polar por nota.

Uso desde un notebook:
    from polar.patron import calcular_patron, graficar_patron

    patron = calcular_patron(polar_alineado, segmentos_por_toma, nombres_notas, i_ref=i_ref)
    graficar_patron(patron, nombres_notas, mics=mics, angulos=angulos)
"""

import numpy as np
import plotly.graph_objects as go


def calcular_patron(polar_alineado, segmentos_por_toma, nombres_notas, i_ref=0, i_az_ref=0):
    """
    Calcula el RMS de cada mic normalizado en dos pasos:

      1. Divide por RMS(mic_ref) en la misma toma → corrige nivel de la cantante
      2. Divide por el valor en i_az_ref (ej: 0°)  → patrón relativo al frente

    Parámetros
    ----------
    polar_alineado     : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    segmentos_por_toma : list[dict]     salida de tensor_notas — uno por ángulo
    nombres_notas      : list[str]      lista de nombres de notas (eje 0)
    i_ref              : int            índice del mic_ref en el tensor (default: 0)
    i_az_ref           : int            índice del ángulo de referencia (default: 0 → 0°)

    Retorna
    -------
    patron : np.ndarray  (n_notas x n_angulos x n_mics)
             (RMS_mic / RMS_ref_toma) / (RMS_mic_0° / RMS_ref_0°)
             0 dB = nivel en el ángulo de referencia.
             np.nan donde la nota no fue detectada.
    """
    n_angulos, n_mics, _ = polar_alineado.shape
    n_notas               = len(nombres_notas)

    patron = np.full((n_notas, n_angulos, n_mics), np.nan, dtype=np.float32)

    for i_nota, nombre in enumerate(nombres_notas):
        for i_az in range(n_angulos):
            seg = segmentos_por_toma[i_az].get(nombre)
            if seg is None:
                continue

            ini = seg['inicio_sample']
            fin = seg['fin_sample']
            if fin <= ini:
                continue

            ventana = polar_alineado[i_az, :, ini:fin]           # (n_mics, largo)
            rms     = np.sqrt(np.mean(ventana ** 2, axis=1))     # (n_mics,)
            rms_ref = rms[i_ref]

            if rms_ref < 1e-10:
                continue

            patron[i_nota, i_az, :] = rms / rms_ref              # paso 1

        # Paso 2: normalizar por el valor en el ángulo de referencia (0°)
        val_0 = patron[i_nota, i_az_ref, :]                       # (n_mics,)
        valido = ~np.isnan(val_0) & (val_0 > 1e-10)
        patron[i_nota, :, valido] /= val_0[valido]

    return patron


def graficar_patron(patron, nombres_notas, mics, angulos, i_mic=None,
                    en_db=True, titulo=None, width=700, height=700):
    """
    Grafica el patrón polar normalizado.

    Por defecto grafica todas las notas en un mismo gráfico polar para el mic
    indicado. Si i_mic es None, usa el primer mic que no sea ref (índice 1).

    Parámetros
    ----------
    patron        : np.ndarray   (n_notas x n_angulos x n_mics)  salida de calcular_patron
    nombres_notas : list[str]    nombres de las notas (eje 0 del patron)
    mics          : list         etiquetas de mics  (ej: ['ref', 1, ..., 19])
    angulos       : list[int]    ángulos medidos    (ej: [0, 10, ..., 180])
    i_mic         : int o None   índice del mic a graficar. None → mic 1 (índice 1)
    en_db         : bool         True → eje radial en dB re mic_ref. False → lineal
    titulo        : str o None   título del gráfico
    width, height : int          tamaño en píxeles
    """
    if i_mic is None:
        i_mic = 1  # primer mic del array (índice 0 es ref)

    label_mic = f"mic_{mics[i_mic]}" if mics else f"mic {i_mic}"
    titulo    = titulo or f"Patrón polar — {label_mic}"

    # Espejamos 0–180 a 0–360 para que quede circular
    angulos_full = angulos + angulos[::-1]
    theta        = angulos_full  # Plotly acepta grados directamente

    fig = go.Figure()

    for i_nota, nombre in enumerate(nombres_notas):
        r_mitad = patron[i_nota, :, i_mic]  # (n_angulos,)

        if np.all(np.isnan(r_mitad)):
            continue  # nota no detectada en ninguna toma

        # Espejo: lado derecho = misma magnitud en sentido inverso
        r_full = np.concatenate([r_mitad, r_mitad[::-1]])

        if en_db:
            with np.errstate(divide='ignore', invalid='ignore'):
                r_plot = 20 * np.log10(np.where(r_full > 0, r_full, np.nan))
        else:
            r_plot = r_full

        # Marcamos con NaN las tomas donde no se detectó la nota
        validas = ~np.isnan(r_plot)
        if not validas.any():
            continue

        fig.add_trace(go.Scatterpolar(
            r     = r_plot,
            theta = theta,
            name  = nombre,
            mode  = 'lines+markers',
            line  = dict(width=2),
        ))

    fig.update_layout(
        title       = titulo,
        polar       = dict(
            angularaxis = dict(direction='clockwise', rotation=90),
            radialaxis  = dict(
                title = "dB re 0°" if en_db else "RMS relativo a 0°",
            ),
        ),
        showlegend  = True,
        width       = width,
        height      = height,
    )

    fig.show()
