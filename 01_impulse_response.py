import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve
from pathlib import Path

# ─────────────────────────────────────────────
# RUTAS
# ─────────────────────────────────────────────

# Carpeta donde están los sweeps grabados por cada micrófono
ruta_sweep = Path(r"D:\UNTREF\IMA\TP5 - PATRON POLAR\TP5-Polar-Plots\data\audio\sweep")

# Carpeta donde vamos a guardar las IRs
# Si no existe la crea automáticamente
ruta_ir = Path(r"D:\UNTREF\IMA\TP5 - PATRON POLAR\TP5-Polar-Plots\data\audio\IR")
ruta_ir.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# CARGAR EL SWEEP EMITIDO
# ─────────────────────────────────────────────

# Cargamos el sweep original que emitió el dodecaedro
sweep_emitido, sr = sf.read(ruta_sweep / "LogSwp_60_12000_-6_dBFS_44k_PCM24.wav")

print(f"Sweep emitido cargado — Sample rate: {sr} Hz — Duración: {len(sweep_emitido)/sr:.2f} s")

# ─────────────────────────────────────────────
# CALCULAR EL FILTRO INVERSO
# ─────────────────────────────────────────────

# Para un sweep logarítmico el filtro inverso es simplemente
# el sweep dado vuelta en el tiempo
# Esto funciona porque el sweep logarítmico tiene la propiedad
# de que su inverso es él mismo time-reversed
filtro_inverso = sweep_emitido[::-1]

# ─────────────────────────────────────────────
# CALCULAR Y GUARDAR LA IR DE CADA MICRÓFONO
# ─────────────────────────────────────────────

for i in range(1, 20):

    # Armamos el nombre del archivo del sweep grabado por este micrófono
    archivo_sweep = ruta_sweep / f"mic_{i}_ang_sweep.wav"

    # Cargamos el sweep grabado por este micrófono
    sweep_grabado, sr_grabado = sf.read(archivo_sweep)

    # Verificamos que el sample rate coincida con el sweep emitido
    # Si no coinciden algo está mal y avisamos
    if sr_grabado != sr:
        print(f"⚠️  Mic {i}: sample rate no coincide ({sr_grabado} Hz vs {sr} Hz)")
        continue

    # Calculamos la IR convoluccionando el sweep grabado con el filtro inverso
    # fftconvolve usa FFT internamente, es más rápido que convolución directa
    # mode='full' genera la señal completa, el pico queda en el centro
    ir = fftconvolve(sweep_grabado, filtro_inverso, mode='full')

    # Normalizamos la IR para que el pico máximo sea 1
    # Esto evita problemas de clipping al guardar el archivo
    ir = ir / np.max(np.abs(ir))

    # Armamos el nombre del archivo de salida
    archivo_ir = ruta_ir / f"mic_{i}_IR.wav"

    # Guardamos la IR como archivo WAV de 32 bits flotante
    # Usamos float porque la IR puede tener valores negativos y muy pequeños
    sf.write(archivo_ir, ir, sr, subtype='FLOAT')

    print(f"Mic {i:2d} → IR guardada: {archivo_ir.name} — Duración: {len(ir)/sr:.2f} s")

print(f"\nIRs guardadas en: {ruta_ir}")