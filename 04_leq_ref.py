# -*- coding: utf-8 -*-
"""
Calcula el LEQ calibrado de uno o varios microfonos para cada toma.

Uso: python leq.py
"""

import numpy as np
import soundfile as sf
from pathlib import Path
import csv

# -- Configuracion -------------------------------------------------------------
# SOLO CAMBIA ESTO:
MICS     = ["1", "2", "3", "4", "5", "6", "7", "8", "9","10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "ref"]  # mics que queres medir
DINAMICA = "forte"                        # "forte" o "piano"
# ------------------------------------------------------------------------------

RUTA_CAL    = Path("data/audio/cal")
RUTA_OUTPUT = Path("output/leq_por_microfono/forte")
RUTA_OUTPUT.mkdir(exist_ok=True)

NIV_CAL_DB  = 94.0
P_REF       = 20e-6
ANGULOS     = list(range(0, 190, 10))

# -- Funcion para calcular el LEQ ----------------------------------------------
def calcular_leq(signal, factor_cal):
    signal_cal = signal * factor_cal
    rms = np.sqrt(np.mean(signal_cal ** 2))
    leq = 20 * np.log10(rms / P_REF)
    return leq

# -- Bucle principal por microfono ---------------------------------------------
for MIC in MICS:

    print(f"\n{'='*50}")
    print(f"  MICROFONO: mic_{MIC}  |  DINAMICA: {DINAMICA}")
    print(f"{'='*50}")

    # Rutas especificas para este microfono
    ARCHIVO_CAL = f"mic_{MIC}_ang_cal.wav"
    RUTA_MED    = Path(f"data/audio/array/{DINAMICA}/mic_{MIC}")
    NOMBRE_MED  = f"mic_{MIC}_ang_{DINAMICA}_{{angulo}}.wav"
    ARCHIVO_CSV = f"leq_mic_{MIC}_{DINAMICA}.csv"

    # -- Calibracion -----------------------------------------------------------
    signal_cal, sr_cal = sf.read(RUTA_CAL / ARCHIVO_CAL)

    if signal_cal.ndim > 1:
        signal_cal = signal_cal[:, 0]

    rms_digital = np.sqrt(np.mean(signal_cal ** 2))
    nivel_dbfs  = 20 * np.log10(rms_digital)
    p_cal_rms   = P_REF * 10 ** (NIV_CAL_DB / 20)
    factor_cal  = p_cal_rms / rms_digital

    print(f"  Archivo cal:      {ARCHIVO_CAL}")
    print(f"  RMS digital:      {rms_digital:.6f}")
    print(f"  Nivel RMS:        {nivel_dbfs:.2f} dBFS")
    print(f"  Factor cal:       {factor_cal:.6f} Pa/unidad\n")

    # -- Calcular LEQ para cada toma -------------------------------------------
    resultados = []

    for angulo in ANGULOS:

        archivo_med = RUTA_MED / NOMBRE_MED.format(angulo=angulo)

        if not archivo_med.exists():
            print(f"  [SKIP] No se encontro: {archivo_med.name}")
            continue

        signal_med, sr_med = sf.read(archivo_med)

        if signal_med.ndim > 1:
            signal_med = signal_med[:, 0]

        if sr_med != sr_cal:
            print(f"  [WARN] Ang {angulo}: sample rate no coincide ({sr_med} vs {sr_cal} Hz)")
            continue

        leq = calcular_leq(signal_med, factor_cal)

        resultados.append({
            'Angulo (°)'   : angulo,
            'Duracion (s)' : round(len(signal_med) / sr_med, 2),
            'LEQ (dB SPL)' : round(leq, 2)
        })

        print(f"  Ang {angulo:>4} -> LEQ: {leq:.2f} dB SPL  ({len(signal_med)/sr_med:.2f} s)")

    # -- Guardar CSV -----------------------------------------------------------
    with open(RUTA_OUTPUT / ARCHIVO_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Angulo (°)', 'Duracion (s)', 'LEQ (dB SPL)'])
        writer.writeheader()
        writer.writerows(resultados)

    print(f"\n  CSV guardado en: {RUTA_OUTPUT / ARCHIVO_CSV}")

    # -- Resumen estadistico ---------------------------------------------------
    leqs = np.array([r['LEQ (dB SPL)'] for r in resultados])
    print(f"\n  LEQ promedio:  {leqs.mean():.2f} dB SPL")
    print(f"  LEQ maximo:    {leqs.max():.2f} dB SPL  (ang {ANGULOS[np.argmax(leqs)]})")
    print(f"  LEQ minimo:    {leqs.min():.2f} dB SPL  (ang {ANGULOS[np.argmin(leqs)]})")
    print(f"  Variacion:     {leqs.max() - leqs.min():.2f} dB")