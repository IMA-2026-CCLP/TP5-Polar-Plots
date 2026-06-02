# -*- coding: utf-8 -*-
"""
Alinea dos grabaciones del microfono de referencia usando GCC-PHAT
y muestra el resultado en un grafico de Plotly.

Uso: python alinear_ref.py
"""

import numpy as np
import soundfile as sf
from pathlib import Path
from scipy.fft import rfft, irfft
from scipy.signal import hilbert
import plotly.graph_objects as go

# -- Configuracion -------------------------------------------------------------
RUTA_REF        = Path("data/audio/array/forte/mic_ref")
ANGULO_A        = 0     # angulo de referencia fijo
ANGULO_B        = 10    # angulo a alinear con el de referencia
MODO_GRAFICO    = "ambas"  # "envolvente", "señal", "ambas"
SEGUNDOS_MOSTRAR = 10   # cuantos segundos mostrar en el grafico
MAX_DESFASE_SEG = 4   # desfase maximo esperado entre tomas en segundos
                         # si el resultado sigue siendo malo, aumentalo
# ------------------------------------------------------------------------------

# -- Funcion GCC-PHAT ----------------------------------------------------------
def gcc_phat(signal_a, signal_b, sr, max_desfase_seg):
    # La GCC-PHAT es mas robusta ante ruido y reverberacion que la correlacion
    # cruzada tradicional. Normaliza la correlacion por su magnitud, conservando
    # solo la informacion de fase que es menos afectada por reflexiones y ruido.

    # Longitud para la FFT
    n = len(signal_a) + len(signal_b) - 1
    n_fft = 2 ** int(np.ceil(np.log2(n)))

    # FFT de ambas señales
    A = rfft(signal_a, n=n_fft)
    B = rfft(signal_b, n=n_fft)

    # Correlacion cruzada en frecuencia
    G = A * np.conj(B)

    # Normalizacion PHAT: escalamos por 1/|G| conservando solo la fase
    G_phat = G / (np.abs(G) + 1e-10)

    # Volvemos al dominio del tiempo y centramos con fftshift
    correlacion = np.fft.fftshift(irfft(G_phat, n=n_fft))

    # Lags posibles en samples
    lags = np.arange(-n_fft // 2, n_fft // 2)

    # Limitamos la busqueda al rango de desfase maximo esperado
    # Esto evita que el algoritmo encuentre picos falsos fuera del rango fisico
    max_lag = int(max_desfase_seg * sr)
    mascara = np.abs(lags) <= max_lag
    correlacion_ventana = np.abs(correlacion.copy())
    correlacion_ventana[~mascara] = 0

    # El pico dentro de la ventana es el desfase real
    desfase_samples = lags[np.argmax(correlacion_ventana)]

    return desfase_samples

# -- Cargar los dos audios -----------------------------------------------------
archivo_a = RUTA_REF / f"mic_ref_ang_forte_{ANGULO_A}.wav"
archivo_b = RUTA_REF / f"mic_ref_ang_forte_{ANGULO_B}.wav"

signal_a, sr   = sf.read(archivo_a)
signal_b, sr_b = sf.read(archivo_b)

if sr != sr_b:
    raise ValueError("Los audios tienen diferentes tasas de muestreo")

print(f"Cargado: {archivo_a.name}  ({len(signal_a)/sr:.2f} s)")
print(f"Cargado: {archivo_b.name}  ({len(signal_b)/sr:.2f} s)")

# -- Calcular desfase ----------------------------------------------------------
desfase    = gcc_phat(signal_a, signal_b, sr, MAX_DESFASE_SEG)
desfase_ms = desfase / sr * 1000

print(f"\nDesfase detectado: {desfase} samples  ({desfase_ms:.2f} ms)")

# -- Alinear signal_b ----------------------------------------------------------
if desfase > 0:
    signal_b_alineada  = signal_b[desfase:]
    signal_a_recortada = signal_a[:len(signal_b_alineada)]
elif desfase < 0:
    signal_a_recortada = signal_a[-desfase:]
    signal_b_alineada  = signal_b[:len(signal_a_recortada)]
else:
    signal_a_recortada = signal_a
    signal_b_alineada  = signal_b

largo = min(len(signal_a_recortada), len(signal_b_alineada))
signal_a_recortada = signal_a_recortada[:largo]
signal_b_alineada  = signal_b_alineada[:largo]

# -- Calcular envolventes ------------------------------------------------------
envolvente_a = np.abs(hilbert(signal_a_recortada))
envolvente_b = np.abs(hilbert(signal_b_alineada))

# -- Downsampling visual -------------------------------------------------------
t              = np.arange(largo) / sr
samples_mostrar = int(SEGUNDOS_MOSTRAR * sr)
n_puntos        = 5000
factor          = samples_mostrar // n_puntos
largo_ajustado  = (samples_mostrar // factor) * factor

env_a_ds     = envolvente_a[:largo_ajustado].reshape(-1, factor).max(axis=1)
env_b_ds     = envolvente_b[:largo_ajustado].reshape(-1, factor).max(axis=1)
sig_a_ds     = signal_a_recortada[:largo_ajustado].reshape(-1, factor).mean(axis=1)
sig_b_ds     = signal_b_alineada[:largo_ajustado].reshape(-1, factor).mean(axis=1)
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
    title=f"mic_ref: ang {ANGULO_A}° vs ang {ANGULO_B}° — desfase: {desfase} samples ({desfase_ms:.2f} ms)",
    xaxis_title="Tiempo (s)",
    yaxis_title="Amplitud",
    legend=dict(x=0, y=1)
)

fig.show()
print(f"\nListo. MAX_DESFASE_SEG={MAX_DESFASE_SEG}s — si el resultado es malo, ajusta ese valor.")