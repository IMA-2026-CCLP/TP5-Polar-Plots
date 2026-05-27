"""
filtrar_wavs.py
───────────────
Aplica un filtro FIR pasa altos de fase lineal a todos los WAVs
dentro de una carpeta (recursivo, respeta subcarpetas mic1/, mic2/...).

Filtro: FIR Kaiser, pasa altos, fc = 100 Hz, fase lineal exacta.
El delay fijo introducido es idéntico en todos los archivos
y no afecta la sincronización posterior por cross-correlación.

Requiere: pip install numpy soundfile scipy
"""

import numpy as np
import soundfile as sf
from scipy.signal import firwin, kaiserord, filtfilt
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
CARPETA_ENTRADA = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\medicion_juli_mic_ref\forte"
CARPETA_SALIDA  = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\medicion_juli_mic_ref\forte_processed"

FC_HZ           = 100     # frecuencia de corte en Hz
RIPPLE_DB       = 60      # atenuación en la banda de rechazo (dB)
                          # 60 dB es más que suficiente para ruido de baja
WIDTH_HZ        = 40      # ancho de la banda de transición en Hz
                          # 40 Hz → filtro empieza a atajar desde ~60 Hz
                          # bajalo a 20 Hz si querés corte más abrupto
                          # (aumenta el orden del filtro)
# ───────────────────────────────────────────────────────────────────────────────

def disenar_filtro(sr):
    """
    Diseña el FIR Kaiser pasa altos para el sample rate dado.
    Devuelve los coeficientes h y el orden N.
    """
    nyq = sr / 2.0
    width_norm = WIDTH_HZ / nyq      # ancho de transición normalizado

    # kaiserord calcula el orden mínimo para cumplir ripple y ancho
    N, beta = kaiserord(RIPPLE_DB, width_norm)
    if N % 2 == 0:
        N += 1  # FIR pasa altos requiere orden impar

    fc_norm = FC_HZ / nyq
    h = firwin(N, fc_norm, window=('kaiser', beta), pass_zero=False)

    delay_ms = (N // 2) / sr * 1000
    return h, N, delay_ms

def cargar_mono(path):
    signal, sr = sf.read(str(path), dtype='float32')
    if signal.ndim > 1:
        signal = signal[:, 0]
    return signal, sr

def procesar():
    entrada = Path(CARPETA_ENTRADA)
    salida  = Path(CARPETA_SALIDA)

    wavs = sorted(entrada.rglob('*.wav'))
    if not wavs:
        print(f"No se encontraron WAVs en {entrada}")
        return

    print(f"Archivos encontrados: {len(wavs)}")

    # Diseñar filtro con el sr del primer archivo
    sig0, sr0 = cargar_mono(wavs[0])
    h, orden, delay_ms = disenar_filtro(sr0)

    print(f"\nFiltro FIR Kaiser pasa altos:")
    print(f"  fc            = {FC_HZ} Hz")
    print(f"  Banda de trans = {FC_HZ - WIDTH_HZ//2}–{FC_HZ + WIDTH_HZ//2} Hz")
    print(f"  Atenuación     = {RIPPLE_DB} dB")
    print(f"  Orden          = {orden} coeficientes")
    print(f"  Delay fijo     = {delay_ms:.2f} ms  (igual en todos los archivos)")
    print(f"  Método         = filtfilt (delay = 0 efectivo, fase lineal exacta)\n")

    # filtfilt aplica el filtro dos veces (ida y vuelta) →
    # delay neto = 0, fase exactamente lineal, atenuación doble (~120 dB)
    errores = 0
    for i, wav in enumerate(wavs, 1):
        rel = wav.relative_to(entrada)
        try:
            sig, sr = cargar_mono(wav)

            if sr != sr0:
                h_local, _, _ = disenar_filtro(sr)
                print(f"  [sr distinto] rediseñando filtro para {sr} Hz")
            else:
                h_local = h

            filtrado = filtfilt(h_local, [1.0], sig).astype(np.float32)

            destino = salida / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(destino), filtrado, sr, subtype='PCM_24')

            print(f"  [{i:>3}/{len(wavs)}] {str(rel)}")

        except Exception as e:
            print(f"  [ERROR] {rel}: {e}")
            errores += 1

    print(f"\n── Listo ──────────────────────────────────────────────")
    print(f"  Guardado en: {salida}")
    print(f"  Procesados:  {len(wavs) - errores} / {len(wavs)}")
    if errores:
        print(f"  Errores:     {errores}")

if __name__ == '__main__':
    procesar()