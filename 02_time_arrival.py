import numpy as np       # para operaciones matemáticas con arrays
import soundfile as sf   # para leer archivos de audio .wav
import csv               # para escribir archivos CSV
from pathlib import Path # para manejar rutas de carpetas y archivos

# ─────────────────────────────────────────────
# RUTAS Y PARÁMETROS
# ─────────────────────────────────────────────

# Carpeta donde están las IRs calculadas
ruta_ir = Path(r"D:\UNTREF\IMA\TP5 - PATRON POLAR\TP5-Polar-Plots\data\audio\IR")

# Carpeta donde vamos a guardar los resultados
# Si no existe, la crea automáticamente
ruta_output = Path(r"D:\UNTREF\IMA\TP5 - PATRON POLAR\TP5-Polar-Plots\output")
ruta_output.mkdir(exist_ok=True)

# Archivo CSV dentro de la carpeta output
ruta_csv = ruta_output / "distancias_micrófonos.csv"

# Distancia nominal a la que se suponía que estaban todos los micrófonos (en metros)
DISTANCIA_NOMINAL = 2.5

# Velocidad del sonido en aire a temperatura ambiente (en metros por segundo)
VELOCIDAD_SONIDO = 343

# Ventana de búsqueda del pico directo en la IR (en milisegundos)
# Buscamos solo en los primeros 20ms porque el sonido directo siempre
# llega antes que cualquier reflejo del auditorio
VENTANA_MS = 20

# ─────────────────────────────────────────────
# FUNCIÓN PARA ENCONTRAR EL TIEMPO DE ARRIBO
# ─────────────────────────────────────────────

def encontrar_tiempo_arribo(ir, sr):
    # Calculamos cuántos samples corresponden a la ventana de búsqueda
    ventana_samples = int(VENTANA_MS / 1000 * sr)
    
    # Buscamos el pico máximo dentro de la ventana inicial de la IR
    # Este pico corresponde al sonido directo, antes de que lleguen los reflejos
    # Usamos el valor absoluto porque el pico puede ser positivo o negativo
    primer_pico = np.argmax(np.abs(ir[:ventana_samples]))
    
    # Convertimos el índice del pico a tiempo en segundos
    tiempo_arribo = primer_pico / sr
    
    return primer_pico, tiempo_arribo

# ─────────────────────────────────────────────
# CARGAR IRs Y CALCULAR DISTANCIAS
# ─────────────────────────────────────────────

# Primero cargamos la IR del Mic 1 para usarla como referencia
# El Mic 1 estaba a 2.5m medido con cinta métrica
ir_ref, sr = sf.read(ruta_ir / "mic_1_IR.wav")
pico_ref, tiempo_ref = encontrar_tiempo_arribo(ir_ref, sr)

print(f"Sample rate: {sr} Hz")
print(f"Mic 1 (referencia) → pico en sample {pico_ref} ({tiempo_ref*1000:.3f} ms)\n")

# Lista donde vamos a guardar los resultados de cada micrófono
resultados = []

# Agregamos el Mic 1 como referencia con desfase cero
resultados.append({
    'Microfono'                        : 1,
    'Sample pico'                      : pico_ref,
    'Tiempo arribo (ms)'               : round(tiempo_ref * 1000, 3),
    'Desfase respecto Mic1 (samples)'  : 0,
    'Desfase respecto Mic1 (ms)'       : 0.0,
    'Distancia real (m)'               : DISTANCIA_NOMINAL,
    'Diferencia respecto nominal (cm)' : 0.0,
    'Montaje'                          : 'Pie (referencia)'
})

# Ahora procesamos los micrófonos 2 al 19
for i in range(2, 20):

    # Cargamos la IR de este micrófono
    ir, sr_i = sf.read(ruta_ir / f"mic_{i}_IR.wav")

    # Verificamos que el sample rate coincida
    if sr_i != sr:
        print(f"⚠️  Mic {i}: sample rate no coincide ({sr_i} Hz vs {sr} Hz)")
        continue

    # Encontramos el tiempo de arribo del sonido directo en esta IR
    pico, tiempo_arribo = encontrar_tiempo_arribo(ir, sr)

    # Calculamos el desfase respecto al Mic 1 (referencia)
    # Si es positivo: el sonido llegó después → está más lejos
    # Si es negativo: el sonido llegó antes → está más cerca
    desfase_samples = pico - pico_ref
    desfase_tiempo = desfase_samples / sr

    # Calculamos la distancia real a partir del desfase
    diferencia_distancia = desfase_tiempo * VELOCIDAD_SONIDO
    distancia_real = DISTANCIA_NOMINAL + diferencia_distancia

    # Pasamos la diferencia a centímetros para que sea más fácil de interpretar
    diferencia_cm = diferencia_distancia * 100

    # Determinamos el tipo de montaje
    # Micrófonos 1, 2, 18 y 19 estaban en pie (posición más precisa)
    # El resto estaban colgados del barral
    if i in [2, 18, 19]:
        montaje = 'Pie'
    else:
        montaje = 'Barral'

    # Guardamos los resultados de este micrófono
    resultados.append({
        'Microfono'                        : i,
        'Sample pico'                      : pico,
        'Tiempo arribo (ms)'               : round(tiempo_arribo * 1000, 3),
        'Desfase respecto Mic1 (samples)'  : desfase_samples,
        'Desfase respecto Mic1 (ms)'       : round(desfase_tiempo * 1000, 3),
        'Distancia real (m)'               : round(distancia_real, 4),
        'Diferencia respecto nominal (cm)' : round(diferencia_cm, 2),
        'Montaje'                          : montaje
    })

# ─────────────────────────────────────────────
# GUARDAR RESULTADOS EN CSV
# ─────────────────────────────────────────────

campos = [
    'Microfono',
    'Sample pico',
    'Tiempo arribo (ms)',
    'Desfase respecto Mic1 (samples)',
    'Desfase respecto Mic1 (ms)',
    'Distancia real (m)',
    'Diferencia respecto nominal (cm)',
    'Montaje'
]

with open(ruta_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=campos)
    writer.writeheader()
    writer.writerows(resultados)

print(f"CSV guardado en: {ruta_csv}")

# ─────────────────────────────────────────────
# MOSTRAR RESUMEN EN PANTALLA
# ─────────────────────────────────────────────

print(f"\n{'Mic':>4} {'Pico(s)':>10} {'T.arribo(ms)':>14} {'Desfase(s)':>12} {'Desfase(ms)':>12} {'Dist real(m)':>14} {'Dif nom(cm)':>13} {'Montaje':>16}")
print("-" * 100)

for r in resultados:
    print(f"{r['Microfono']:>4} "
          f"{r['Sample pico']:>10} "
          f"{r['Tiempo arribo (ms)']:>14} "
          f"{r['Desfase respecto Mic1 (samples)']:>12} "
          f"{r['Desfase respecto Mic1 (ms)']:>12} "
          f"{r['Distancia real (m)']:>14} "
          f"{r['Diferencia respecto nominal (cm)']:>13} "
          f"{r['Montaje']:>16}")