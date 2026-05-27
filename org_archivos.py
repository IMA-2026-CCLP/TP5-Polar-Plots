import os
import shutil
import re
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
# Cambiá esta ruta a la carpeta donde tenés todos tus WAVs
CARPETA_ORIGEN = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_processed"
# ───────────────────────────────────────────────────────────────────────────────

# Patrones válidos:
#   mic_1_ang_forte_0.wav
#   mic_1_ang_piano_0.wav
#   mic_1_ang_cal-01.wav  (calibración, sin ángulo al final)
PATRON = re.compile(
    r'^mic_(\d+)_ang_(forte|piano|cal\S*)(?:_(\d+))?\.wav$',
    re.IGNORECASE
)

def clasificar(nombre):
    """Devuelve (dinamica, mic_num) o None si no matchea."""
    m = PATRON.match(nombre)
    if not m:
        return None
    mic_num = int(m.group(1))
    dinamica_raw = m.group(2).lower()
    if dinamica_raw.startswith('cal'):
        dinamica = 'cal'
    elif dinamica_raw == 'forte':
        dinamica = 'forte'
    elif dinamica_raw == 'piano':
        dinamica = 'piano'
    else:
        return None
    return dinamica, mic_num

def organizar():
    origen = Path(CARPETA_ORIGEN)
    if not origen.exists():
        print(f"ERROR: No existe la carpeta: {origen}")
        return

    wavs = list(origen.glob('*.wav'))
    print(f"WAVs encontrados: {len(wavs)}")

    movidos = 0
    ignorados = 0
    errores = 0

    for wav in wavs:
        resultado = clasificar(wav.name)
        if resultado is None:
            print(f"  [ignorado]  {wav.name}")
            ignorados += 1
            continue

        dinamica, mic_num = resultado
        destino_dir = origen / dinamica / f"mic{mic_num}"
        destino_dir.mkdir(parents=True, exist_ok=True)

        destino = destino_dir / wav.name
        if destino.exists():
            print(f"  [ya existe] {wav.name}")
            continue

        try:
            shutil.move(str(wav), str(destino))
            print(f"  [ok] {wav.name}  →  {dinamica}/mic{mic_num}/")
            movidos += 1
        except Exception as e:
            print(f"  [ERROR] {wav.name}: {e}")
            errores += 1

    print()
    print(f"── Resumen ───────────────────")
    print(f"  Movidos:   {movidos}")
    print(f"  Ignorados: {ignorados}")
    print(f"  Errores:   {errores}")
    print()
    print("Estructura creada:")
    for din in ['cal', 'forte', 'piano']:
        d = origen / din
        if d.exists():
            mics = sorted(d.iterdir())
            total = sum(len(list(m.glob('*.wav'))) for m in mics)
            print(f"  {din}/  ({len(mics)} mics, {total} archivos)")
            for mic_dir in mics:
                n = len(list(mic_dir.glob('*.wav')))
                print(f"    {mic_dir.name}/  ({n} archivos)")

if __name__ == '__main__':
    organizar()