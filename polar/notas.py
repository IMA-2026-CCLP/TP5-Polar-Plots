# -*- coding: utf-8 -*-
"""
polar/notas.py

Detección de notas con pyin y construcción del tensor máscara de notas.

Uso desde un notebook:
    from polar.notas import tensor_notas, NOTAS_FA_MAYOR

    N, nombres_notas, segs = tensor_notas(polar_alineado, i_ref=i_ref, sr=SR, angulos=angulos)

    # Extraer solo Fa4 de todos los ángulos y mics:
    i_nota = nombres_notas.index('Fa4')
    R = polar_alineado * N[i_nota, :, np.newaxis, :]   # (n_angulos, n_mics, n_samples)
"""

import numpy as np
import pandas as pd
import librosa
from IPython.display import Audio


NOTAS_FA_MAYOR = {
    'Fa4' : 349.23,
    'Sol4': 392.00,
    'La4' : 440.00,
    'Sib4': 466.16,
    'Do5' : 523.25,
    'Re5' : 587.33,
    'Mi5' : 659.25,
    'Fa5' : 698.46,
}


def detectar_notas_pyin(signal, sr, notas=None, min_duracion_ms=300,
                        margen_inicio_ms=50, margen_fin_ms=50, umbral_confianza=0.2):
    """
    Detecta el F0 de una señal 1D y asigna cada frame a la nota más cercana.

    Parámetros
    ----------
    signal            : np.ndarray 1D  señal de audio
    sr                : int            sample rate (Hz)
    notas             : dict           {nombre: freq_Hz}. Default: NOTAS_FA_MAYOR
    min_duracion_ms   : float          duración mínima de un segmento en ms
    margen_inicio_ms  : float          ms a recortar al inicio del segmento (evita el ataque)
    margen_fin_ms     : float          ms a recortar al final del segmento (evita la transición)
    umbral_confianza  : float          umbral mínimo de probabilidad voiced

    Retorna
    -------
    segmentos : dict  {nombre_nota: {'inicio_sample': int, 'fin_sample': int}}
                      Solo incluye notas que fueron detectadas.
    """
    if notas is None:
        notas = NOTAS_FA_MAYOR

    f0, voiced_flag, voiced_prob = librosa.pyin(
        signal.astype(np.float32),
        fmin=librosa.note_to_hz('E4'),
        fmax=librosa.note_to_hz('G5'),
        sr=sr,
        fill_na=np.nan,
    )

    voiced_flag = voiced_flag & (voiced_prob >= umbral_confianza)

    hop_length             = 512
    nombres_notas          = list(notas.keys())
    margen_inicio_samples  = int(margen_inicio_ms / 1000 * sr)
    freqs_notas        = np.array(list(notas.values()))
    min_frames         = int(min_duracion_ms / 1000 * sr / hop_length)
    margen_fin_samples = int(margen_fin_ms   / 1000 * sr)

    # Interpolamos F0 para suavizar saltos en transiciones
    f0_suavizado = f0.copy()
    voiced_idx   = np.where(voiced_flag)[0]
    if len(voiced_idx) > 1:
        f0_suavizado = np.interp(np.arange(len(f0)), voiced_idx, f0[voiced_idx])

    nota_por_frame = []
    for i, freq in enumerate(f0_suavizado):
        if not voiced_flag[i] or np.isnan(freq):
            nota_por_frame.append(None)
            continue
        distancias = np.abs(np.log2(freq / freqs_notas))
        nota_por_frame.append(nombres_notas[np.argmin(distancias)])

    # Encontrar segmentos continuos
    segmentos_raw = []
    nota_actual   = nota_por_frame[0]
    inicio        = 0

    for i, nota in enumerate(nota_por_frame[1:], start=1):
        if nota != nota_actual:
            if nota_actual is not None:
                segmentos_raw.append({
                    'nota'         : nota_actual,
                    'inicio_sample': inicio * hop_length,
                    'fin_sample'   : i * hop_length,
                    'duracion'     : i - inicio,
                })
            nota_actual = nota
            inicio      = i

    if nota_actual is not None:
        segmentos_raw.append({
            'nota'         : nota_actual,
            'inicio_sample': inicio * hop_length,
            'fin_sample'   : len(nota_por_frame) * hop_length,
            'duracion'     : len(nota_por_frame) - inicio,
        })

    # Filtrar segmentos cortos y quedarse con el más largo por nota
    segmentos_validos = [s for s in segmentos_raw if s['duracion'] >= min_frames]

    resultado = {}
    for nombre in nombres_notas:
        candidatos = [s for s in segmentos_validos if s['nota'] == nombre]
        if candidatos:
            mejor = max(candidatos, key=lambda s: s['duracion'])
            ini   = mejor['inicio_sample'] + margen_inicio_samples
            fin   = mejor['fin_sample'] - margen_fin_samples
            if ini < fin:
                resultado[nombre] = {
                    'inicio_sample': ini,
                    'fin_sample'   : fin,
                }

    return resultado


def tensor_notas(polar_alineado, i_ref=10, sr=44100, notas=None, angulos=None, **kwargs):
    """
    Construye un tensor máscara de notas usando mic_10 para la detección de F0.

    mic_10 está a 90° de elevación (directamente sobre la cabeza de la cantante),
    lo que da una señal más estable y una detección de notas más precisa que el
    mic_ref externo.

    Parámetros
    ----------
    polar_alineado : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    i_ref          : int            índice del mic para pyin (default: 10 → mic_10)
    sr             : int            sample rate (Hz)
    notas          : dict           {nombre: freq_Hz}. Default: NOTAS_FA_MAYOR
    angulos        : list           etiquetas de ángulo para el print
    **kwargs                        parámetros extra para detectar_notas_pyin

    Retorna
    -------
    N                  : np.ndarray bool  (n_notas x n_angulos x n_samples)
                         N[i_nota, i_az, :] == True durante el segmento de esa nota
    nombres_notas      : list[str]        nombres en el orden del eje 0
    segmentos_por_toma : list[dict]       resultado bruto de detectar_notas_pyin por toma
    """
    if notas is None:
        notas = NOTAS_FA_MAYOR

    n_angulos, n_mics, n_samples = polar_alineado.shape
    nombres_notas = list(notas.keys())
    n_notas       = len(nombres_notas)
    etiquetas     = angulos if angulos is not None else list(range(n_angulos))

    N = np.zeros((n_notas, n_angulos, n_samples), dtype=bool)
    segmentos_por_toma = []

    header = "  " + "  ".join(f"{n:<5}" for n in nombres_notas)
    print(f"{'Toma':>7}  {header}")
    print("  " + "-" * (9 + 7 * n_notas))

    for i_az in range(n_angulos):
        signal = polar_alineado[i_az, i_ref, :]
        segs   = detectar_notas_pyin(signal, sr, notas=notas, **kwargs)
        segmentos_por_toma.append(segs)

        fila = []
        for i_nota, nombre in enumerate(nombres_notas):
            if nombre in segs:
                ini = segs[nombre]['inicio_sample']
                fin = min(segs[nombre]['fin_sample'], n_samples)
                if ini < fin:
                    N[i_nota, i_az, ini:fin] = True
                fila.append("  OK ")
            else:
                fila.append("  -- ")

        label = etiquetas[i_az]
        print(f"  {str(label):>5}°  " + "  ".join(fila))

    n_detectadas = sum(1 for i in range(n_notas) if N[i].any())
    print(f"\n  Tensor N : {N.shape}  (n_notas x n_angulos x n_samples)")
    print(f"  Notas detectadas en al menos una toma: {n_detectadas}/{n_notas}")

    return N, nombres_notas, segmentos_por_toma


def validar_deteccion(polar_alineado, segmentos_por_toma, nombres_notas,
                      i_mic=10, sr=44100, notas=None, angulos=None, tolerancia_cents=50):
    """
    Valida la detección de notas comparando el pico FFT de cada segmento
    con la frecuencia esperada de la nota. Devuelve un DataFrame con los resultados.

    Parámetros
    ----------
    polar_alineado     : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    segmentos_por_toma : list[dict]     salida de tensor_notas
    nombres_notas      : list[str]      lista de nombres de notas
    i_mic              : int            mic a usar para la validación (default: 10)
    sr                 : int            sample rate (Hz)
    notas              : dict           {nombre: freq_Hz}. Default: NOTAS_FA_MAYOR
    angulos            : list           etiquetas de ángulo para el print
    tolerancia_cents   : float          margen aceptable en cents (default: 50)

    Retorna
    -------
    df : pd.DataFrame  filas=notas, columnas=ángulos, valores=cents de error
                       NaN donde la nota no fue detectada
    """
    if notas is None:
        notas = NOTAS_FA_MAYOR

    n_angulos  = polar_alineado.shape[0]
    etiquetas  = [f"{a}°" for a in angulos] if angulos else [str(i) for i in range(n_angulos)]
    datos      = {et: {} for et in etiquetas}

    for i_az in range(n_angulos):
        et = etiquetas[i_az]
        for nombre in nombres_notas:
            seg = segmentos_por_toma[i_az].get(nombre)
            if seg is None:
                datos[et][nombre] = float('nan')
                continue

            ini    = seg['inicio_sample']
            fin    = seg['fin_sample']
            signal = polar_alineado[i_az, i_mic, ini:fin]

            freqs  = np.fft.rfftfreq(len(signal), d=1/sr)
            mag    = np.abs(np.fft.rfft(signal))

            # Buscar el pico dentro de ±300 cents de la frecuencia esperada
            # para evitar que los armónicos superiores dominen el argmax
            f_esp   = notas[nombre]
            f_min   = f_esp * 2 ** (-300 / 1200)
            f_max   = f_esp * 2 ** ( 300 / 1200)
            mascara = (freqs >= f_min) & (freqs <= f_max)
            if mascara.any():
                f_pico = freqs[mascara][np.argmax(mag[mascara])]
            else:
                f_pico = freqs[np.argmax(mag)]  # fallback

            cents  = 1200 * np.log2(f_pico / f_esp) if f_pico > 0 else float('nan')
            datos[et][nombre] = round(cents, 1)

    df = pd.DataFrame(datos, index=nombres_notas)

    # Imprimir resumen con OK / WARN
    print(f"Validación detección pyin — mic_{i_mic}  (tolerancia ±{tolerancia_cents} cents)\n")
    ok = warn = ausente = 0
    for et in etiquetas:
        problemas = []
        for nombre in nombres_notas:
            c = datos[et][nombre]
            if np.isnan(c):
                ausente += 1
                problemas.append(f"{nombre}:NaN")
            elif abs(c) > tolerancia_cents:
                warn += 1
                problemas.append(f"{nombre}:{c:+.0f}¢")
            else:
                ok += 1
        estado = "✓" if not problemas else "✗  " + "  ".join(problemas)
        print(f"  {et:>6}  {estado}")

    total = ok + warn + ausente
    print(f"\n  OK: {ok}/{total}   WARN: {warn}   NaN: {ausente}")
    return df


def escuchar(polar_alineado, segmentos_por_toma, nota, i_az, i_mic, sr=44100, mics=None, angulos=None):
    """
    Reproduce un segmento de nota de un mic y toma específicos.

    Parámetros
    ----------
    polar_alineado     : np.ndarray 3D  (n_angulos x n_mics x n_samples)
    segmentos_por_toma : list[dict]     salida de tensor_notas
    nota               : str            nombre de la nota (ej: 'Fa4')
    i_az               : int            índice del ángulo (toma)
    i_mic              : int            índice del mic en el tensor
    sr                 : int            sample rate (Hz)
    mics               : list           para el print (ej: ['ref',1..19])
    angulos            : list           para el print (ej: [0,10..180])
    """
    segs = segmentos_por_toma[i_az]

    if nota not in segs:
        print(f"[WARN] '{nota}' no fue detectada en la toma {angulos[i_az] if angulos else i_az}°")
        return

    ini = segs[nota]['inicio_sample']
    fin = segs[nota]['fin_sample']

    label_az  = f"{angulos[i_az]}°" if angulos  else f"toma {i_az}"
    label_mic = f"mic_{mics[i_mic]}" if mics else f"mic {i_mic}"

    print(f"  {nota}  |  {label_az}  |  {label_mic}  |  {ini/sr:.2f}s – {fin/sr:.2f}s  ({(fin-ini)/sr:.2f}s)")

    signal = polar_alineado[i_az, i_mic, ini:fin]
    return Audio(signal, rate=sr)
