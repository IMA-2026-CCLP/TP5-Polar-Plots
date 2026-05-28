"""
copiar_a_plano.py
═════════════════
Copia todos los WAVs de la estructura:
  Media_processed/forte/mic1/, mic2/, ...
  Media_processed/piano/mic1/, mic2/, ...

A una única carpeta destino plana:
  destino/
    mic_1_ang_forte_0.wav
    mic_1_ang_piano_0.wav
    ...

Requiere: solo librería estándar de Python
"""

import shutil
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

CARPETA_ORIGEN  = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_processed"
CARPETA_DESTINO = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_flat"

# ══════════════════════════════════════════════════════════════

def copiar():
    origen  = Path(CARPETA_ORIGEN)
    destino = Path(CARPETA_DESTINO)
    destino.mkdir(parents=True, exist_ok=True)

    wavs = sorted(origen.rglob('*.wav'))

    print(f"{'═'*55}")
    print(f"  Origen:  {origen}")
    print(f"  Destino: {destino}")
    print(f"  Archivos encontrados: {len(wavs)}")
    print(f"{'═'*55}\n")

    copiados = 0
    existian = 0
    errores  = 0

    for wav in wavs:
        dest_file = destino / wav.name

        if dest_file.exists():
            print(f"  [YA EXISTE] {wav.name}")
            existian += 1
            continue

        try:
            shutil.copy2(str(wav), str(dest_file))
            print(f"  [ok] {wav.parent.name}/{wav.name}")
            copiados += 1
        except Exception as e:
            print(f"  [ERROR] {wav.name}: {e}")
            errores += 1

    print(f"\n{'═'*55}")
    print(f"  Copiados:    {copiados}")
    print(f"  Ya existían: {existian}")
    print(f"  Errores:     {errores}")
    print(f"{'═'*55}\n")

if __name__ == '__main__':
    copiar()