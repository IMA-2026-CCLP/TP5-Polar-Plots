"""
interpolar_mic9.py
──────────────────
Genera los WAVs del micrófono 9 (que no grabó) interpolando
entre el micrófono 8 y el micrófono 10 para cada ángulo.

Método:
  1. Carga mic_8 y mic_10 del mismo ángulo.
  2. Alinea mic_10 respecto a mic_8 por cross-correlación GCC-PHAT en Fourier.
  3. Promedia las muestras temporales (válido porque los delays están compensados).
  4. Guarda como mic_9_ang_forte_XX.wav en mic9/

Requiere: pip install numpy soundfile
"""

import numpy as np
import soundfile as sf
from pathlib import Path
import re

# ── Configuración ──────────────────────────────────────────────────────────────
CARPETA_ENTRADA = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_for_processed\forte"
# mic_9 se crea dentro de CARPETA_ENTRADA/mic9/

DINAMICA        = "forte"
MIC_A           = 8       # micrófono izquierdo al hueco
MIC_B           = 10      # micrófono derecho al hueco
MIC_NUEVO       = 9       # el que vamos a generar

MAX_DELAY_SEG   = 0.01    # ventana de búsqueda GCC-PHAT (10 ms es más que suficiente
                          # para diferencias entre mics adyacentes en un array)
# ───────────────────────────────────────────────────────────────────────────────

PATRON = re.compile(r'mic_(\d+)_ang_(\w+)_(\d+)\.wav', re.IGNORECASE)

def cargar_mono(path):
    sig, sr = sf.read(str(path), dtype='float32')
    if sig.ndim > 1:
        sig = sig[:, 0]
    return sig, sr

def gcc_phat(sig_a, sig_b, sr, max_delay_seg=0.01):
    """
    Calcula el delay de sig_b respecto a sig_a via GCC-PHAT en Fourier.
    Retorna delay en muestras (positivo = sig_b llega después que sig_a).

    Pasos:
      1. FFT de ambas señales (zero-padding a potencia de 2)
      2. Cross-spectrum: A * conj(B)
      3. PHAT: normalizar por |A * conj(B)| → blanqueo de fase
      4. IFFT → función de correlación de fase
      5. Buscar el pico dentro de ±max_delay_seg
    """
    n     = len(sig_a) + len(sig_b) - 1
    n_fft = int(2 ** np.ceil(np.log2(n)))

    # ── 1. FFT ────────────────────────────────────────────────────────────
    A = np.fft.rfft(sig_a, n=n_fft)
    B = np.fft.rfft(sig_b, n=n_fft)

    # ── 2 & 3. Cross-spectrum + blanqueo PHAT ─────────────────────────────
    R     = A * np.conj(B)
    denom = np.abs(R)
    denom[denom < 1e-10] = 1e-10
    R    /= denom                       # solo queda la información de fase

    # ── 4. IFFT → correlación de fase ─────────────────────────────────────
    cc = np.fft.irfft(R, n=n_fft)      # longitud n_fft, lags circulares

    # ── 5. Buscar pico en ±max_delay_seg ──────────────────────────────────
    max_lag = int(max_delay_seg * sr)

    # La IFFT da lags positivos al inicio y negativos al final (circular)
    # Extraemos ambas mitades y buscamos el máximo global
    cc_pos  = cc[:max_lag + 1]                      # lags  0 … +max_lag
    cc_neg  = cc[n_fft - max_lag: n_fft]            # lags -max_lag … -1

    pico_pos = np.argmax(cc_pos)
    pico_neg = np.argmax(cc_neg)

    val_pos  = cc_pos[pico_pos]
    val_neg  = cc_neg[pico_neg]

    if val_pos >= val_neg:
        return int(pico_pos)                        # delay positivo
    else:
        return -int(max_lag - pico_neg)             # delay negativo

def alinear_y_promediar(sig_a, sig_b, delay):
    """
    Desplaza sig_b por -delay muestras para alinearlo con sig_a,
    recorta ambos a la misma longitud y promedia.

    delay > 0 → sig_b llega tarde → adelantamos sig_b (descartamos inicio)
    delay < 0 → sig_b llega antes → adelantamos sig_a
    """
    if delay >= 0:
        b_alineado = sig_b[delay:]
        a_recortado = sig_a[:len(b_alineado)]
    else:
        a_recortado = sig_a[-delay:]
        b_alineado  = sig_b[:len(a_recortado)]

    largo = min(len(a_recortado), len(b_alineado))
    return (a_recortado[:largo] + b_alineado[:largo]) * 0.5

def procesar():
    entrada = Path(CARPETA_ENTRADA)

    # ── Buscar todos los WAVs de mic_A y mic_B ────────────────────────────
    archivos_a = {}   # angulo -> Path
    archivos_b = {}

    for wav in sorted(entrada.rglob('*.wav')):
        m = PATRON.match(wav.name)
        if not m:
            continue
        mic_num  = int(m.group(1))
        dinamica = m.group(2).lower()
        angulo   = int(m.group(3))

        if dinamica != DINAMICA:
            continue
        if mic_num == MIC_A:
            archivos_a[angulo] = wav
        elif mic_num == MIC_B:
            archivos_b[angulo] = wav

    angulos_comunes = sorted(set(archivos_a) & set(archivos_b))

    if not angulos_comunes:
        print(f"No se encontraron pares mic_{MIC_A} / mic_{MIC_B} para dinámica '{DINAMICA}'")
        return

    print(f"Ángulos a interpolar: {angulos_comunes}\n")

    # ── Carpeta de salida para mic9 ───────────────────────────────────────
    salida_dir = entrada / f"mic{MIC_NUEVO}"
    salida_dir.mkdir(exist_ok=True)

    for angulo in angulos_comunes:
        path_a = archivos_a[angulo]
        path_b = archivos_b[angulo]

        sig_a, sr_a = cargar_mono(path_a)
        sig_b, sr_b = cargar_mono(path_b)

        if sr_a != sr_b:
            print(f"  [ERROR] ángulo {angulo}°: sample rates distintos ({sr_a} vs {sr_b}), saltando")
            continue

        sr = sr_a

        # ── GCC-PHAT en Fourier ───────────────────────────────────────────
        delay = gcc_phat(sig_a, sig_b, sr, MAX_DELAY_SEG)

        # ── Promedio post-alineación ──────────────────────────────────────
        interpolado = alinear_y_promediar(sig_a, sig_b, delay)

        # ── Guardar como mic_9 ────────────────────────────────────────────
        nombre   = f"mic_{MIC_NUEVO}_ang_{DINAMICA}_{angulo}.wav"
        destino  = salida_dir / nombre
        sf.write(str(destino), interpolado, sr, subtype='PCM_24')

        signo = '+' if delay >= 0 else ''
        print(f"  [ok] {angulo:>4}°  |  delay mic{MIC_B}→mic{MIC_A}: {signo}{delay} muestras "
              f"({signo}{delay/sr*1000:.3f} ms)  |  → {nombre}")

    print(f"\n── Listo ──────────────────────────────────────────────")
    print(f"  {len(angulos_comunes)} archivos generados en: {salida_dir}")

if __name__ == '__main__':
    procesar()