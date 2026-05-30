# -*- coding: utf-8 -*-
"""
Convierte archivos WAV de 48000 Hz a 44100 Hz, 24 bits, mono.
Si detecta un archivo stereo o multicanal, pregunta al usuario que canal usar.

Uso: python resamplear.py
"""

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from pathlib import Path

# -- Configuracion -------------------------------------------------------------
RUTA_ORIGEN  = Path(r"data/audio/forte/ref")
RUTA_DESTINO = Path(r"data/audio/forte/ref_44")
RUTA_DESTINO.mkdir(parents=True, exist_ok=True)
# ------------------------------------------------------------------------------

# Relacion de resampleo: 44100/48000 = 147/160
UP   = 147
DOWN = 160

# Buscamos todos los WAVs en la carpeta de origen
archivos = sorted(RUTA_ORIGEN.glob("*.wav"))

if not archivos:
    print(f"[ERROR] No se encontraron WAVs en:\n  {RUTA_ORIGEN}")
    raise SystemExit(1)

print(f"Encontrados {len(archivos)} archivos\n")

for archivo in archivos:

    # Cargamos el archivo original
    signal, sr = sf.read(archivo)

    # Verificamos que sea realmente 48000 Hz
    if sr != 48000:
        print(f"[SKIP] {archivo.name} -> sample rate es {sr} Hz, no 48000 Hz")
        continue

    # Si el audio es multicanal preguntamos al usuario que hacer
    if signal.ndim > 1:
        n_canales = signal.shape[1]
        print(f"\n  WARNING: {archivo.name} tiene {n_canales} canales.")
        print(f"  Que queres hacer?")
        print(f"  [0] Promediar todos los canales a mono")

        # Mostramos una opcion por cada canal disponible
        for c in range(n_canales):
            print(f"  [{c+1}] Usar solo el canal {c+1}")

        # Esperamos la respuesta del usuario
        while True:
            respuesta = input(f"  Ingresa tu opcion (0 a {n_canales}): ").strip()

            # Verificamos que la respuesta sea valida
            if respuesta.isdigit() and 0 <= int(respuesta) <= n_canales:
                opcion = int(respuesta)
                break
            else:
                print(f"  Opcion invalida, ingresa un numero entre 0 y {n_canales}")

        if opcion == 0:
            # Promediamos todos los canales
            signal = np.mean(signal, axis=1)
            print(f"  -> promediados {n_canales} canales a mono")
        else:
            # Tomamos el canal elegido (restamos 1 porque los indices arrancan en 0)
            signal = signal[:, opcion - 1]
            print(f"  -> usando canal {opcion}")

    # Calculamos el RMS antes del resampleo para conservar la ganancia
    rms_antes = np.sqrt(np.mean(signal ** 2))

    # Resampleamos de 48000 Hz a 44100 Hz
    signal_44k = resample_poly(signal, UP, DOWN)

    # Corregimos la ganancia para que el RMS sea igual antes y despues del resampleo
    # Esto evita que el resampleo cambie el nivel de la senal
    rms_despues = np.sqrt(np.mean(signal_44k ** 2))
    signal_44k = signal_44k * (rms_antes / rms_despues)

    # Guardamos el archivo en la carpeta destino con el mismo nombre
    # PCM_24 = 24 bits
    ruta_destino = RUTA_DESTINO / archivo.name
    sf.write(ruta_destino, signal_44k, 44100, subtype='PCM_24')

    print(f"OK {archivo.name}  ->  @44100 Hz  24bit  mono\n")

print(f"\nListo. Archivos guardados en:\n  {RUTA_DESTINO}")