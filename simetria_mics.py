"""
simetria_angulos_faltantes.py
══════════════════════════════
Genera los archivos faltantes para los ángulos de mesa 0°, 10° y 20°
aprovechando la simetría izquierda-derecha de la voz cantada.

LÓGICA DE REMAPEO
══════════════════
Cuando la mesa giratoria está a 180°, la fuente apunta en dirección
opuesta a 0°. Por simetría vocal, esto equivale a medir a 0° pero
con el array espejado. El espejo del array invierte el orden de los
micrófonos:

    mic_k  ↔  mic_(20-k)

Por lo tanto, para generar el ángulo faltante ANG_FALTANTE a partir
del ángulo simétrico ANG_SIMETRICO = 180 - ANG_FALTANTE:

    FUENTE:  mic_{20-k}/mic_{20-k}_ang_{din}_{180-ang}.wav
    DESTINO: mic_{k}/mic_{k}_ang_{din}_{ang}.wav

Ejemplos:
    mic_19_ang_forte_180.wav  →  mic_1_ang_forte_0.wav
    mic_15_ang_forte_170.wav  →  mic_5_ang_forte_10.wav
    mic_1_ang_forte_160.wav   →  mic_19_ang_forte_20.wav

REQUIERE: solo librería estándar de Python (shutil)
"""

import shutil
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

# Carpeta raíz que contiene las subcarpetas forte/ y piano/
CARPETA_BASE = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_processed"

# Ángulos de mesa que faltan y sus simétricos
ANGULOS_FALTANTES = {
    0:  180,
    10: 170,
    20: 160,
}

N_MICS = 19

# ══════════════════════════════════════════════════════════════


def mic_espejo(mic_num: int, n_mics: int) -> int:
    """
    Devuelve el micrófono simétrico de mic_num en un array de n_mics.

    El array va de mic_1 (0°) a mic_19 (180°) equiespaciado.
    El espejo de mic_k es mic_(n_mics + 1 - k):
        mic_1  ↔ mic_19
        mic_2  ↔ mic_18
        mic_9  ↔ mic_11
        mic_10 ↔ mic_10  (centro, se mapea a sí mismo)
    """
    return n_mics + 1 - mic_num


def procesar_dinamica(dinamica: str):
    """Aplica el remapeo de simetría para una dinámica dada."""

    carpeta = Path(CARPETA_BASE) / dinamica

    if not carpeta.exists():
        print(f"\n  [ERROR] No se encontró la carpeta: {carpeta}")
        return

    print(f"\n{'═'*60}")
    print(f"  Procesando: {dinamica.upper()}")
    print(f"  Carpeta:    {carpeta}")
    print(f"{'═'*60}")
    print(f"  {'FUENTE':<45}  →  DESTINO")
    print(f"  {'-'*45}     {'-'*45}")

    copiados = 0
    errores  = 0
    existian = 0

    for ang_faltante, ang_simetrico in sorted(ANGULOS_FALTANTES.items()):
        for mic_dest in range(1, N_MICS + 1):

            mic_src = mic_espejo(mic_dest, N_MICS)

            nombre_src  = f"mic_{mic_src}_ang_{dinamica}_{ang_simetrico}.wav"
            nombre_dest = f"mic_{mic_dest}_ang_{dinamica}_{ang_faltante}.wav"

            path_src  = carpeta / f"mic{mic_src}"  / nombre_src
            path_dest = carpeta / f"mic{mic_dest}" / nombre_dest

            if not path_src.exists():
                print(f"  [NO EXISTE] {path_src.relative_to(carpeta)}")
                errores += 1
                continue

            if path_dest.exists():
                print(f"  [YA EXISTE] {nombre_dest}")
                existian += 1
                continue

            path_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path_src), str(path_dest))
            print(f"  {str(path_src.relative_to(carpeta)):<45}  →  "
                  f"{str(path_dest.relative_to(carpeta))}")
            copiados += 1

    total = N_MICS * len(ANGULOS_FALTANTES)
    print(f"\n  Resumen {dinamica.upper()}:")
    print(f"    Copiados:        {copiados} / {total}")
    print(f"    Ya existían:     {existian}")
    print(f"    Fuente faltante: {errores}")


def elegir_dinamica() -> list:
    """Muestra el menú y devuelve la lista de dinámicas a procesar."""
    print("\n╔══════════════════════════════════════════╗")
    print("║   Simetría — ángulos faltantes 0/10/20°  ║")
    print("╠══════════════════════════════════════════╣")
    print("║  1 → forte                               ║")
    print("║  2 → piano                               ║")
    print("║  3 → ambas dinámicas                     ║")
    print("╚══════════════════════════════════════════╝")

    while True:
        opcion = input("\nElegí una opción (1 / 2 / 3): ").strip()
        if opcion == "1":
            return ["forte"]
        elif opcion == "2":
            return ["piano"]
        elif opcion == "3":
            return ["forte", "piano"]
        else:
            print("  Opción inválida. Ingresá 1, 2 o 3.")


def main():
    dinamicas = elegir_dinamica()
    for din in dinamicas:
        procesar_dinamica(din)
    print(f"\n{'═'*60}")
    print("  Listo.")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()