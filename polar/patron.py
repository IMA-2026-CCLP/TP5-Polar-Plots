# -*- coding: utf-8 -*-
"""
polar/patron.py

Cálculo y visualización del patrón polar por nota.

Normalización:
  - Paso 1: divide por RMS(mic_10) en cada toma → mic_10 está a 90° de elevación
            (siempre sobre la cabeza de la cantante) y su nivel es constante
            ante cualquier rotación azimutal.
  - Paso 2: divide por el valor en 0° → patrón relativo al frente.

Uso desde un notebook:
    from polar.patron import calcular_patron, graficar_patron

    i_mic10 = mics.index(10)
    patron = calcular_patron(polar_alineado, segmentos_por_toma, nombres_notas, i_ref=i_mic10)
    graficar_patron(patron, nombres_notas, mics=mics, angulos=angulos)
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def calcular_patron(polar_alineado, segmentos_por_toma, nombres_notas, i_ref=10, i_az_ref=0):
    """
    Calcula el RMS de cada mic normalizado en dos pasos:

      1. Divide por RMS(mic_10) en la misma toma → mic_10 está a 90° de elevación,
         siempre sobre la cabeza de la cantante; su nivel es constante ante rotaciones
         azimutales y compensa variaciones de nivel entre notas y entre tomas.
      2. Divide por el valor en i_az_ref (ej: 0°) → patrón relativo al frente.

    Parámetros
    ----------
    polar_alineado     : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    segmentos_por_toma : list[dict]     salida de tensor_notas — uno por ángulo
    nombres_notas      : list[str]      lista de nombres de notas (eje 0)
    i_ref              : int            índice del mic normalizador (default: 10 → mic_10)
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

    # Paso 2: normalizar por la media de todas las notas en el ángulo de referencia.
    # Usar una sola referencia global mantiene las notas comparables entre sí:
    # 0 dB = nivel promedio en 0° a través de todas las notas.
    val_0_global = np.nanmean(patron[:, i_az_ref, :], axis=0)     # (n_mics,)
    val_0_global[np.isnan(val_0_global) | (val_0_global < 1e-10)] = np.nan
    patron = patron / val_0_global[np.newaxis, np.newaxis, :]

    return patron


def graficar_patron(patron, nombres_notas, mics, angulos, i_mic=None,
                    en_db=True, rango_db=(-10, 6), titulo=None, width=700, height=700):
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

    # theta: 0, 10, ..., 350  (36 puntos, paso 10°)
    # El espejo correcto es: [0..180, 190..350] = [r[0..18], r[17..1]]
    paso   = angulos[1] - angulos[0]                      # normalmente 10°
    theta  = list(range(0, 361, paso))                    # 37 puntos (cierra en 360°=0°)

    fig = go.Figure()

    for i_nota, nombre in enumerate(nombres_notas):
        r_mitad = patron[i_nota, :, i_mic]  # (n_angulos,)  0°→180°

        if np.all(np.isnan(r_mitad)):
            continue  # nota no detectada en ninguna toma

        # Espejo: 190°→350° es el reverso de 170°→10°, más cierre en 360°=0°
        r_full = np.concatenate([r_mitad, r_mitad[-2:0:-1], [r_mitad[0]]])

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

    # Círculo de referencia en 0 dB — fuera de la leyenda para que siempre sea visible
    r_ref = 0 if en_db else 1
    fig.add_trace(go.Scatterpolar(
        r          = [r_ref] * len(theta),
        theta      = theta,
        mode       = 'lines',
        line       = dict(color='black', width=1.5, dash='dash'),
        showlegend = False,
        hoverinfo  = 'skip',
    ))

    fig.update_layout(
        title       = titulo,
        polar       = dict(
            angularaxis = dict(direction='clockwise', rotation=90),
            radialaxis  = dict(
                title    = "dB re 0°" if en_db else "RMS relativo a 0°",
                range    = list(rango_db) if en_db else None,
                autorange= False if en_db else True,
            ),
        ),
        showlegend  = True,
        width       = width,
        height      = height,
    )

    fig.show()


def graficar_patron_ref(polar_alineado, segmentos_por_toma, nombres_notas, mics, angulos,
                        i_mic=None, rango_db=(-20, 6), titulo=None, width=700, height=700):
    """
    Calcula y grafica el patrón polar normalizando por mic_ref.

    Para cada nota:
      1. Calcula RMS en dBFS por mic y ángulo.
      2. Corrige variación de nivel entre tomas usando mic_ref.
      3. Normaliza a 0°.
    Grafica todas las notas en un mismo plot polar.

    Parámetros
    ----------
    polar_alineado     : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    segmentos_por_toma : list[dict]     salida de tensor_notas
    nombres_notas      : list[str]      lista de nombres de notas
    mics               : list           etiquetas de mics  (ej: ['ref', 1, ..., 19])
    angulos            : list[int]      ángulos medidos    (ej: [0, 10, ..., 180])
    i_mic              : int o None     índice del mic a graficar. None → mic 1
    titulo             : str o None     título del gráfico
    width, height      : int            tamaño en píxeles
    """
    if i_mic is None:
        i_mic = mics.index(1) if 1 in mics else 1

    label_mic = f"mic_{mics[i_mic]}"
    titulo    = titulo or f"Patrón polar — {label_mic}"

    paso  = angulos[1] - angulos[0]
    theta = list(range(0, 361, paso))
    cols  = [f"{a}°" for a in angulos]

    fig = go.Figure()

    for nota in nombres_notas:
        datos = {}
        for I_AZ, col in enumerate(cols):
            seg = segmentos_por_toma[I_AZ].get(nota)
            if seg is None:
                datos[col] = [np.nan] * len(mics)
                continue
            ventana    = polar_alineado[I_AZ, :, seg['inicio_sample']:seg['fin_sample']]
            rms        = np.sqrt(np.mean(ventana ** 2, axis=1))
            datos[col] = 20 * np.log10(rms + 1e-12)

        df = pd.DataFrame(datos, index=[f"mic_{m}" for m in mics])

        variacion = df.loc['mic_ref'] - df.loc['mic_ref'].max()
        df_norm   = df.copy()
        df_norm.loc['mic_ref'] = variacion
        for idx in df_norm.index[1:]:
            df_norm.loc[idx] = df.loc[idx] - variacion
        for idx in df_norm.index[1:]:
            df_norm.loc[idx] = df_norm.loc[idx] - df_norm.loc[idx, '0°']

        r_mitad = df_norm.loc[label_mic].values
        if np.all(np.isnan(r_mitad)):
            continue

        r_full = np.concatenate([r_mitad, r_mitad[-2:0:-1], [r_mitad[0]]])
        fig.add_trace(go.Scatterpolar(
            r=r_full, theta=theta, mode='lines+markers', name=nota, line=dict(width=2)
        ))

    fig.add_trace(go.Scatterpolar(
        r=[0] * len(theta), theta=theta, mode='lines',
        line=dict(color='black', dash='dash', width=1.5), showlegend=False, hoverinfo='skip',
    ))

    fig.update_layout(
        title      = titulo,
        polar      = dict(
            angularaxis = dict(direction='clockwise', rotation=90),
            radialaxis  = dict(title='dB re 0°', range=list(rango_db), autorange=False),
        ),
        showlegend = True,
        width      = width,
        height     = height,
    )
    fig.show()
