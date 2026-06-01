# -*- coding: utf-8 -*-
"""
Arma el tensor de mediciones [azimuth x elevacion x samples] y lo guarda como .npy

tensor[i_azimuth, i_elevacion, sample]

i_azimuth   = posicion de la mesa    (0, 10, ..., 180)
i_elevacion = numero de microfono   (mic_1 a mic_19)
sample      = señal de audio completa, rellenada con ceros al final si es necesario

Uso: python armar_tensor.py
"""

import numpy as np
import soundfile as sf
from pathlib import Path

# -- Configuracion -------------------------------------------------------------
RUTA_ARRAY     = Path("data/audio/array/forte")
RUTA_OUTPUT    = Path("data/tensores")
RUTA_OUTPUT.mkdir(parents=True, exist_ok=True)

ARCHIVO_TENSOR = "forte.npy"

ANGULOS        = list(range(0, 190, 10))  # 0, 10, 20, ... 180
MICS           = list(range(1, 20))       # 1, 2, 3, ... 19
# ------------------------------------------------------------------------------

# -- PASO 1: calcular el largo maximo de todos los audios ----------------------
print("=" * 50)
print("PASO 1: Calculando largo maximo")
print("=" * 50)

largos = []

for angulo in ANGULOS:
    archivo = RUTA_ARRAY / "mic_10" / f"mic_10_ang_forte_{angulo}.wav" # tomo el mic 10 como mi "referencia" 
    if not archivo.exists():
        print(f"  [SKIP] No se encontro: {archivo.name}")
        continue
    signal, sr = sf.read(archivo)
    largos.append(len(signal))
    print(f"  Ang {angulo:>4}° → {len(signal)} samples  ({len(signal)/sr:.2f} s)")

# Usamos el largo maximo para no perder informacion
# Las tomas mas cortas se rellenaran con ceros al final
largo_max = max(largos)
print(f"\n  Largo maximo: {largo_max} samples  ({largo_max/sr:.2f} s)")

# -- PASO 2: armar el tensor ---------------------------------------------------
print(f"\n{'='*50}")
print("PASO 2: Armando tensor")
print("=" * 50)

n_azimuth   = len(ANGULOS)
n_elevacion = len(MICS)

# El tensor se inicializa con ceros
# Las tomas mas cortas quedaran con ceros al final automaticamente
tensor = np.zeros((n_azimuth, n_elevacion, largo_max), dtype=np.float32)

for i_az, angulo in enumerate(ANGULOS):
    for i_el, mic in enumerate(MICS):
        archivo = RUTA_ARRAY / f"mic_{mic}" / f"mic_{mic}_ang_forte_{angulo}.wav"

        if not archivo.exists():
            print(f"  [SKIP] No se encontro: {archivo.name}")
            continue

        signal, _ = sf.read(archivo)

        # Ponemos la señal en el tensor
        # El resto del tensor ya esta en cero por inicializacion
        tensor[i_az, i_el, :len(signal)] = signal

    print(f"  Ang {angulo:>4}° → OK")

# -- PASO 3: guardar -----------------------------------------------------------
print(f"\n{'='*50}")
print("PASO 3: Guardando tensor")
print("=" * 50)

np.save(RUTA_OUTPUT / ARCHIVO_TENSOR, tensor)

print(f"  Guardado: {RUTA_OUTPUT / ARCHIVO_TENSOR}")
print(f"  Shape:    {tensor.shape}  (azimuth x elevacion x samples)")
print(f"  Tamaño:   {tensor.nbytes / 1024 / 1024:.1f} MB")
print(f"  SR:       {sr} Hz")
print(f"  Duracion: {largo_max/sr:.2f} s")