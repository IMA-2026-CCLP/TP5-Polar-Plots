# -*- coding: utf-8 -*-
"""
Organiza los WAVs en subcarpetas por dinamica y angulo O por dinamica y microfono.

Convencion de nombres:  mic_{N}_ang_{dinamica}_{angulo}.wav

Modo angulo:
    data/audio/
        forte/
            ang_0/
                mic_1_ang_forte_0.wav
                mic_2_ang_forte_0.wav
        piano/
            ang_0/
                ...

Modo microfono:
    data/audio/
        forte/
            mic_1/
                mic_1_ang_forte_0.wav
                mic_1_ang_forte_10.wav
        piano/
            mic_1/
                ...

Uso: python organizar.py
"""

import re
import shutil
from pathlib import Path

# -- Configuracion -------------------------------------------------------------
ORIGEN  = Path(r"D:\UNTREF\IMA\TP5 - PATRON POLAR\procesados\media")
DESTINO = Path(r"D:\UNTREF\IMA\TP5 - PATRON POLAR\TP5-Polar-Plots\data\audio\array")
MOVER   = False       # True = mover archivos | False = copiar (mas seguro)
MODO    = "microfono" # "angulo" o "microfono"
# ------------------------------------------------------------------------------

# Patron para extraer microfono, dinamica y angulo del nombre del archivo
# Ejemplo: mic_7_ang_forte_100.wav -> mic=7, dinamica='forte', angulo=100
# Ejemplo: mic_ref_ang_forte_100.wav -> mic='ref', dinamica='forte', angulo=100
patron = re.compile(r"mic_(\w+)_ang_(forte|piano)_(\d+)\.wav$", re.IGNORECASE)

# Buscamos todos los WAVs en la carpeta de origen
archivos = sorted(ORIGEN.glob("*.wav"))

# Si no hay archivos avisamos y salimos
if not archivos:
    print(f"[ERROR] No se encontraron WAVs en:\n  {ORIGEN}")
    raise SystemExit(1)

# Verificamos que el modo sea valido
if MODO not in ("angulo", "microfono"):
    print(f"[ERROR] MODO debe ser 'angulo' o 'microfono', no '{MODO}'")
    raise SystemExit(1)

print(f"Modo: {MODO}")
print(f"Encontrados {len(archivos)} archivos\n")

# Contador para el reporte final
conteo = {}

for archivo in archivos:

    # Intentamos extraer microfono, dinamica y angulo del nombre
    m = patron.search(archivo.name)

    # Si el nombre no coincide con el patron esperado lo saltamos
    if not m:
        print(f"[SKIP] No se pudo procesar: {archivo.name}")
        continue

    # Extraemos los datos del nombre del archivo
    mic      = m.group(1).lower()    # por ejemplo: '1', '2', 'ref'
    dinamica = m.group(2).lower()    # 'forte' o 'piano'
    angulo   = int(m.group(3))       # por ejemplo: 0, 10, 20... 180

    # Armamos la carpeta destino segun el modo elegido
    if MODO == "angulo":
        # data/audio/forte/ang_0/
        carpeta = DESTINO / dinamica / f"ang_{angulo}"
    else:
        # data/audio/forte/mic_1/
        carpeta = DESTINO / dinamica / f"mic_{mic}"

    # Creamos la carpeta si no existe
    carpeta.mkdir(parents=True, exist_ok=True)

    # Armamos la ruta completa del archivo destino
    destino = carpeta / archivo.name

    # Movemos o copiamos segun la configuracion
    if MOVER:
        shutil.move(str(archivo), destino)
    else:
        shutil.copy2(str(archivo), destino)

    # Actualizamos el contador
    clave = (dinamica, f"ang_{angulo}" if MODO == "angulo" else f"mic_{mic}")
    conteo[clave] = conteo.get(clave, 0) + 1

# -- Reporte -------------------------------------------------------------------
accion = "movidos" if MOVER else "copiados"
total  = sum(conteo.values())

print("\n" + "-"*50)
print(f"  {total} archivos {accion} en modo '{MODO}':\n")

for (dinamica, subcarpeta) in sorted(conteo):
    print(f"  {dinamica}/{subcarpeta:<10}  ->  {conteo[(dinamica, subcarpeta)]} archivos")

print("-"*50)
print(f"\n  Destino: {DESTINO}")