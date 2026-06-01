# -*- coding: utf-8 -*-
"""
polar/utils.py

Funciones de procesamiento general.

Uso desde un notebook:
    from polar.utils import hpf, detectar_onsets, alinear
"""

import numpy as np
from scipy.signal import butter, sosfilt


def hpf(signal, sr, frecuencia_corte=200):
    """
    Aplica un filtro pasa altos Butterworth de orden 4.

    Parámetros
    ----------
    signal          : array-like  señal de audio
    sr              : int         sample rate (Hz)
    frecuencia_corte: float       frecuencia de corte en Hz (default: 200)

    Retorna
    -------
    signal_filtrada : np.ndarray  señal filtrada
    """
    sos = butter(4, frecuencia_corte, btype='high', fs=sr, output='sos')
    return sosfilt(sos, signal)


def detectar_onsets(datos, sr=44100, ventana_ms=50, segundos_ruido=2, margen_db=10, pre_onset_ms=100, etiquetas=None):
    """
    Detecta el onset de cada fila de `datos` midiendo el ruido de fondo
    en los primeros segundos y aplicando un umbral relativo a ese nivel.

    Parámetros
    ----------
    datos          : np.ndarray 2D  (n_filas x n_samples)
    sr             : int            sample rate (Hz)
    ventana_ms     : float          tamaño de ventana RMS en ms
    segundos_ruido : float          segundos iniciales para medir ruido de fondo
    margen_db      : float          dB por encima del ruido para detectar onset
    pre_onset_ms   : float          ms de margen antes del onset detectado
    etiquetas      : list o None    etiquetas para el print (ej: angulos o mics)

    Retorna
    -------
    onsets : np.ndarray 1D (n_filas,)  onset de cada fila en samples
    """
    n_filas           = datos.shape[0]
    ventana_samples   = int(ventana_ms   / 1000 * sr)
    samples_ruido     = int(segundos_ruido       * sr)
    pre_onset_samples = int(pre_onset_ms / 1000 * sr)
    onsets            = np.zeros(n_filas, dtype=int)

    for i in range(n_filas):
        signal = datos[i, :]
        label  = etiquetas[i] if etiquetas is not None else i

        # Ruido de fondo en los primeros segundos
        rms_ruido = np.sqrt(np.mean(signal[:samples_ruido] ** 2))

        # Umbral = ruido + margen en dB
        umbral = rms_ruido * 10 ** (margen_db / 20)

        # RMS en ventanas sucesivas
        n_ventanas   = (len(signal) - ventana_samples) // ventana_samples
        rms_ventanas = np.array([
            np.sqrt(np.mean(signal[j * ventana_samples:(j + 1) * ventana_samples] ** 2))
            for j in range(n_ventanas)
        ])

        indices_activos = np.where(rms_ventanas > umbral)[0]

        if len(indices_activos) == 0:
            print(f"  [WARN] {label}: no se detectó onset, probá bajar margen_db")
            onsets[i] = 0
        else:
            onset_raw = indices_activos[0] * ventana_samples
            onsets[i] = max(0, onset_raw - pre_onset_samples)
            print(
                f"  {str(label):>6} → "
                f"onset: {onsets[i]:>8} samples  ({onsets[i] / sr * 1000:.0f} ms)  |  "
                f"ruido: {20 * np.log10(rms_ruido + 1e-12):.1f} dBFS  |  "
                f"umbral: {20 * np.log10(umbral + 1e-12):.1f} dBFS"
            )

    return onsets


def alinear(tensor, onsets_mic10, onsets_ref=None, i_ref=0, sr=44100, gap_ms=0):
    """
    Alinea el tensor completo usando los onsets del mic_10.
    El mic_ref se alinea usando sus propios onsets (independiente del mic_10).

    Parámetros
    ----------
    tensor       : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    onsets_mic10 : np.ndarray 1D  (n_angulos,)  onset por toma del mic_10
    onsets_ref   : np.ndarray 1D  (n_angulos,)  onset por toma del mic_ref
                                                 si es None no se corrige el ref
    i_ref        : int            índice del mic_ref en el tensor (default: 0)
    sr           : int            sample rate (Hz)
    gap_ms       : float          ms de silencio a dejar antes de cada onset

    Retorna
    -------
    tensor_alineado : np.ndarray 3D  (n_angulos x n_mics x largo)
    """
    n_angulos, n_mics, n_samples = tensor.shape
    gap_samples = int(gap_ms / 1000 * sr)

    # Largo final basado en el onset más tardío del mic_10
    onset_max = onsets_mic10.max()
    largo     = n_samples - onset_max + gap_samples

    tensor_alineado = np.zeros((n_angulos, n_mics, largo), dtype=np.float32)

    for i_az in range(n_angulos):

        # -- Todos los mics (incluido ref por ahora): onset del mic_10 -----
        inicio     = max(0, onsets_mic10[i_az] - gap_samples)
        disponible = n_samples - inicio
        if disponible >= largo:
            tensor_alineado[i_az, :, :] = tensor[i_az, :, inicio:inicio + largo]
        else:
            tensor_alineado[i_az, :, :disponible] = tensor[i_az, :, inicio:]

        # -- Solo el ref: reemplazamos con su propio onset -----------------
        if onsets_ref is not None:
            inicio_ref = max(0, onsets_ref[i_az] - gap_samples)
            tensor_alineado[i_az, i_ref, :] = 0  # borramos lo que se copió antes

            disponible_ref = n_samples - inicio_ref
            if disponible_ref >= largo:
                tensor_alineado[i_az, i_ref, :] = tensor[i_az, i_ref, inicio_ref:inicio_ref + largo]
            else:
                tensor_alineado[i_az, i_ref, :disponible_ref] = tensor[i_az, i_ref, inicio_ref:]

    print(f"  Tensor alineado.")
    print(f"  Shape original  : {tensor.shape}")
    print(f"  Shape alineado  : {tensor_alineado.shape}")
    print(f"  Onset máximo    : {onset_max} samples  ({onset_max / sr * 1000:.0f} ms)")
    print(f"  Gap inicial     : {gap_samples} samples  ({gap_ms:.0f} ms)")

    return tensor_alineado