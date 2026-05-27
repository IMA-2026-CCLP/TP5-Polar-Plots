"""
interpolar_mic9_temporal.py
═══════════════════════════
Genera los WAVs del micrófono 9 interpolando en el dominio temporal
entre mic 8 (70°) y mic 10 (90°).

MÉTODO:
  1. Cargar mic 8 y mic 10.
  2. Alinear mic 10 respecto a mic 8 por GCC-PHAT.
  3. Promedio simple de las dos señales alineadas (t=0.5, equidistante).
  4. El nivel resultante es el promedio de los niveles de mic 8 y mic 10.

Simple, robusto, nivel siempre correcto con mics calibrados.

REQUIERE: pip install numpy soundfile
"""

import numpy as np
import soundfile as sf
from pathlib import Path
import re

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

CARPETA_ENTRADA = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_processed\forte"
DINAMICA        = "forte"

MIC_FALTANTE = 9
MIC_IZQ      = 8    # 70°
MIC_DER      = 10   # 90°

MAX_DELAY_SEG = 0.05   # ventana de búsqueda GCC-PHAT (50 ms)

# ══════════════════════════════════════════════════════════════

PATRON = re.compile(r'mic_(\d+)_ang_(\w+)_(\d+)\.wav', re.IGNORECASE)


def cargar_mono(path: Path):
    sig, sr = sf.read(str(path), dtype='float32')
    if sig.ndim > 1:
        sig = sig[:, 0]
    return sig, sr


def gcc_phat(sig_a: np.ndarray, sig_ref: np.ndarray,
             sr: int, max_delay_seg: float) -> int:
    """
    Delay de sig_a respecto a sig_ref en muestras.
    Positivo = sig_a llega después.
    """
    n     = len(sig_a) + len(sig_ref) - 1
    n_fft = int(2 ** np.ceil(np.log2(n)))

    A   = np.fft.rfft(sig_a,   n=n_fft)
    REF = np.fft.rfft(sig_ref, n=n_fft)

    R     = A * np.conj(REF)
    denom = np.abs(R)
    denom[denom < 1e-10] = 1e-10
    R    /= denom

    cc      = np.fft.irfft(R, n=n_fft)
    max_lag = int(max_delay_seg * sr)

    cc_pos = cc[:max_lag + 1]
    cc_neg = cc[n_fft - max_lag:]

    pico_pos = int(np.argmax(cc_pos))
    pico_neg = int(np.argmax(cc_neg))

    if cc_pos[pico_pos] >= cc_neg[pico_neg]:
        return pico_pos
    else:
        return -(max_lag - pico_neg)


def alinear(sig: np.ndarray, delay: int, largo: int) -> np.ndarray:
    """Desplaza sig por -delay muestras y recorta a `largo`."""
    if delay > 0:
        sig_al = sig[delay:]
    elif delay < 0:
        sig_al = np.pad(sig, (-delay, 0))
    else:
        sig_al = sig.copy()

    if len(sig_al) >= largo:
        return sig_al[:largo]
    return np.pad(sig_al, (0, largo - len(sig_al)))


def procesar():
    entrada = Path(CARPETA_ENTRADA)

    # ── Descubrir pares mic_8 / mic_10 por ángulo de fuente ──────────────
    archivos_izq = {}
    archivos_der = {}

    for wav in sorted(entrada.rglob('*.wav')):
        m = PATRON.match(wav.name)
        if not m:
            continue
        mic_num  = int(m.group(1))
        dinamica = m.group(2).lower()
        ang      = int(m.group(3))
        if dinamica != DINAMICA:
            continue
        if mic_num == MIC_IZQ:
            archivos_izq[ang] = wav
        elif mic_num == MIC_DER:
            archivos_der[ang] = wav

    angulos = sorted(set(archivos_izq) & set(archivos_der))
    if not angulos:
        print(f"No se encontraron pares mic_{MIC_IZQ}/mic_{MIC_DER}")
        return

    print(f"Ángulos: {angulos}")
    print(f"Método: promedio temporal mic_{MIC_IZQ} + mic_{MIC_DER} "
          f"con alineación GCC-PHAT\n")

    salida_dir = entrada / f"mic{MIC_FALTANTE}"
    salida_dir.mkdir(exist_ok=True)

    for ang_fuente in angulos:
        sig_izq, sr_izq = cargar_mono(archivos_izq[ang_fuente])
        sig_der, sr_der = cargar_mono(archivos_der[ang_fuente])

        if sr_izq != sr_der:
            print(f"  [ERROR] {ang_fuente}°: sr distintos, saltando")
            continue

        sr    = sr_izq
        largo = min(len(sig_izq), len(sig_der))
        sig_izq = sig_izq[:largo]
        sig_der = sig_der[:largo]

        # ── Alinear mic_der respecto a mic_izq ───────────────────────────
        delay = gcc_phat(sig_der, sig_izq, sr, MAX_DELAY_SEG)
        sig_der_al = alinear(sig_der, delay, largo)

        # ── Promedio simple ───────────────────────────────────────────────
        sig_mic9 = ((sig_izq.astype(np.float64) +
                     sig_der_al.astype(np.float64)) * 0.5).astype(np.float32)

        # Niveles para verificación
        rms_izq  = 20 * np.log10(np.sqrt(np.mean(sig_izq**2))    + 1e-10)
        rms_der  = 20 * np.log10(np.sqrt(np.mean(sig_der**2))    + 1e-10)
        rms_out  = 20 * np.log10(np.sqrt(np.mean(sig_mic9**2))   + 1e-10)

        pico = np.max(np.abs(sig_mic9))
        if pico > 1.0:
            sig_mic9 /= pico

        nombre  = f"mic_{MIC_FALTANTE}_ang_{DINAMICA}_{ang_fuente}.wav"
        destino = salida_dir / nombre
        sf.write(str(destino), sig_mic9, sr, subtype='PCM_24')

        print(f"  {ang_fuente:>4}°  |  "
              f"mic{MIC_IZQ}: {rms_izq:.1f} dBFS  "
              f"mic{MIC_DER}: {rms_der:.1f} dBFS  "
              f"delay: {delay:+d} muestras  "
              f"salida: {rms_out:.1f} dBFS  →  {nombre}")

    print(f"\n── Listo ──────────────────────────────────────")
    print(f"  Archivos en: {salida_dir}")

if __name__ == '__main__':
    procesar()