# -*- coding: utf-8 -*-
"""
Alinea dos grabaciones del microfono de referencia usando deteccion de onset
y muestra el resultado en un grafico de Plotly.

Uso: python alinear_ref.py
"""

import numpy as np
import soundfile as sf
from pathlib import Path
from scipy.signal import hilbert
import plotly.graph_objects as go

# -- Configuracion -------------------------------------------------------------
RUTA_REF         = Path("data/audio/array/forte/mic_ref")
ANGULO_A         = 0      # angulo de referencia fijo
ANGULO_B         = 10     # angulo a alinear
MODO_GRAFICO     = "ambas" # "envolvente", "señal", "ambas"
SEGUNDOS_MOSTRAR = 10     # cuantos segundos mostrar en el grafico

# Parametros de deteccion de onset
VENTANA_MS       = 50     # tamaño de la ventana RMS en milisegundos
UMBRAL_DBFS     = -40     # umbral en dBFS para detectar inicio del canto
UMBRAL          = 10 ** (UMBRAL_DBFS / 20)  # conversion a amplitud digital
                          # si no detecta bien el inicio, ajusta este valor
# ------------------------------------------------------------------------------

# -- Funcion para detectar onset -----------------------------------------------
def detectar_onset(signal, sr, ventana_ms, umbral):
    # Calculamos cuantos samples tiene la ventana
    ventana_samples = int(ventana_ms / 1000 * sr)

    # Calculamos el RMS en ventanas sucesivas
    # Recorremos la señal de ventana en ventana
    rms_ventanas = []
    for i in range(0, len(signal) - ventana_samples, ventana_samples):
        ventana = signal[i:i + ventana_samples]
        rms = np.sqrt(np.mean(ventana ** 2))
        rms_ventanas.append(rms)

    rms_ventanas = np.array(rms_ventanas)

    # Buscamos la primera ventana donde el RMS supera el umbral
    indices_activos = np.where(rms_ventanas > umbral)[0]

    if len(indices_activos) == 0:
        print(f"  [WARN] No se detecto onset con umbral={umbral}, proba un valor mas bajo")
        return 0

    # El onset es el sample donde empieza la primera ventana activa
    onset_sample = indices_activos[0] * ventana_samples

    return onset_sample

# -- Cargar los dos audios -----------------------------------------------------
archivo_a = RUTA_REF / f"mic_ref_ang_forte_{ANGULO_A}.wav"


archivo_b = RUTA_REF / f"mic_ref_ang_forte_{ANGULO_B}.wav"

signal_a, sr   = sf.read(archivo_a)
signal_b, sr_b = sf.read(archivo_b)

if sr != sr_b:
    raise ValueError("Los audios tienen diferentes tasas de muestreo")

print(f"Cargado: {archivo_a.name}  ({len(signal_a)/sr:.2f} s)")
print(f"Cargado: {archivo_b.name}  ({len(signal_b)/sr:.2f} s)")

# -- Detectar onset en cada señal ----------------------------------------------
onset_a = detectar_onset(signal_a, sr, VENTANA_MS, UMBRAL)
onset_b = detectar_onset(signal_b, sr, VENTANA_MS, UMBRAL)

print(f"\nOnset ang {ANGULO_A}°: sample {onset_a}  ({onset_a/sr*1000:.2f} ms)")
print(f"Onset ang {ANGULO_B}°: sample {onset_b}  ({onset_b/sr*1000:.2f} ms)")
print(f"Diferencia: {abs(onset_a - onset_b)} samples  ({abs(onset_a - onset_b)/sr*1000:.2f} ms)")

# -- Recortar ambas señales desde su onset -------------------------------------
signal_a_recortada = signal_a[onset_a:]
signal_b_recortada = signal_b[onset_b:]

# Usamos la longitud minima para que ambas tengan el mismo largo
largo = min(len(signal_a_recortada), len(signal_b_recortada))
signal_a_recortada = signal_a_recortada[:largo]
signal_b_recortada = signal_b_recortada[:largo]

# -- Calcular envolventes ------------------------------------------------------
envolvente_a = np.abs(hilbert(signal_a_recortada))
envolvente_b = np.abs(hilbert(signal_b_recortada))

# -- Downsampling visual -------------------------------------------------------
samples_mostrar = min(int(SEGUNDOS_MOSTRAR * sr), largo)  # no superar el largo real
n_puntos        = 5000
factor          = samples_mostrar // n_puntos
largo_ajustado  = (samples_mostrar // factor) * factor
largo_ajustado  = min(largo_ajustado, largo)  # aseguramos que no supere el largo

t               = np.arange(largo_ajustado) / sr
# samples_mostrar = int(SEGUNDOS_MOSTRAR * sr)
# n_puntos        = 5000
# factor          = samples_mostrar // n_puntos
# largo_ajustado  = (samples_mostrar // factor) * factor

env_a_ds      = envolvente_a[:largo_ajustado].reshape(-1, factor).max(axis=1)
env_b_ds      = envolvente_b[:largo_ajustado].reshape(-1, factor).max(axis=1)
sig_a_ds      = signal_a_recortada[:largo_ajustado].reshape(-1, factor).mean(axis=1)
sig_b_ds      = signal_b_recortada[:largo_ajustado].reshape(-1, factor).mean(axis=1)
sig_a_orig_ds = signal_a[:largo_ajustado].reshape(-1, factor).mean(axis=1)
sig_b_orig_ds = signal_b[:largo_ajustado].reshape(-1, factor).mean(axis=1)
t_ds          = t[:largo_ajustado].reshape(-1, factor).mean(axis=1)

# -- Graficar ------------------------------------------------------------------
fig = go.Figure()

if MODO_GRAFICO in ("señal", "ambas"):
    fig.add_trace(go.Scatter(
        x=t_ds, y=sig_a_orig_ds,
        name=f"Señal ang {ANGULO_A}° (original)",
        line=dict(color='rgba(0, 0, 255, 0.3)', width=1, dash='dot')
    ))
    fig.add_trace(go.Scatter(
        x=t_ds, y=sig_b_orig_ds,
        name=f"Señal ang {ANGULO_B}° (original)",
        line=dict(color='rgba(255, 0, 0, 0.3)', width=1, dash='dot')
    ))
    fig.add_trace(go.Scatter(
        x=t_ds, y=sig_a_ds,
        name=f"Señal ang {ANGULO_A}° (alineada)",
        line=dict(color='rgba(0, 0, 255, 0.6)', width=1)
    ))
    fig.add_trace(go.Scatter(
        x=t_ds, y=sig_b_ds,
        name=f"Señal ang {ANGULO_B}° (alineada)",
        line=dict(color='rgba(255, 0, 0, 0.6)', width=1)
    ))

if MODO_GRAFICO in ("envolvente", "ambas"):
    fig.add_trace(go.Scatter(
        x=t_ds, y=env_a_ds,
        name=f"Envolvente ang {ANGULO_A}°",
        line=dict(color='blue', width=2),
        fill='tozeroy',
        fillcolor='rgba(0, 0, 255, 0.1)'
    ))
    fig.add_trace(go.Scatter(
        x=t_ds, y=env_b_ds,
        name=f"Envolvente ang {ANGULO_B}°",
        line=dict(color='red', width=2),
        fill='tozeroy',
        fillcolor='rgba(255, 0, 0, 0.1)'
    ))

fig.update_layout(
    title=f"mic_ref: ang {ANGULO_A}° vs ang {ANGULO_B}° — onset A: {onset_a/sr*1000:.0f}ms | onset B: {onset_b/sr*1000:.0f}ms",
    xaxis_title="Tiempo (s)",
    yaxis_title="Amplitud",
    legend=dict(x=0, y=1)
)

fig.show()
print(f"\nListo. Si el onset no esta bien detectado, ajusta UMBRAL={UMBRAL}")