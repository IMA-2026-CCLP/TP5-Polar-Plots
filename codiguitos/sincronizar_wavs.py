"""
sincronizar_wavs.py
───────────────────
Detecta el onset de cada WAV usando un umbral variable por archivo
(piso de ruido estimado en los primeros 3 segundos + margen en dB),
recorta 100ms antes del onset, iguala la duración al archivo más corto
y guarda los resultados en forte_sync/ manteniendo la estructura mic1/, mic2/...

Requiere: pip install numpy soundfile
"""

import numpy as np
import soundfile as sf
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
CARPETA_ENTRADA   = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_for_processed\forte"       # carpeta con subcarpetas mic1/, mic2/...
CARPETA_SALIDA    = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_for_processed\forte_sync"  # se crea sola

PRE_ONSET_MS      = 100   # ms a conservar antes del onset
FRAME_MS          = 20    # tamaño de frame RMS en ms
RUIDO_VENTANA_SEG = 3.0   # segundos iniciales para estimar el piso de ruido
MARGEN_DB         = 12    # dB por encima del piso de ruido para detectar onset
                          # subí a 15-18 si detecta ruido como onset
                          # bajá a 8-10 si corta demasiado tarde
# ───────────────────────────────────────────────────────────────────────────────

def rms_db(signal):
    rms = np.sqrt(np.mean(signal ** 2))
    if rms < 1e-10:
        return -120.0
    return 20 * np.log10(rms)

def detectar_onset(signal, sr):
    """
    Umbral variable por archivo:
    1. Estima el piso de ruido con los primeros RUIDO_VENTANA_SEG segundos.
    2. Umbral = piso + MARGEN_DB.
    3. Devuelve el índice del primer frame que supera ese umbral.
    """
    frame_samples = int(sr * FRAME_MS / 1000)
    n_frames = len(signal) // frame_samples

    # ── Piso de ruido: mediana de los primeros 3 segundos ─────────────────
    frames_ruido = min(int(RUIDO_VENTANA_SEG * sr / frame_samples), n_frames)
    niveles_ruido = [
        rms_db(signal[i * frame_samples:(i + 1) * frame_samples])
        for i in range(frames_ruido)
    ]
    piso_db   = np.median(niveles_ruido)
    threshold = piso_db + MARGEN_DB

    # ── Buscar primer frame sobre el umbral ───────────────────────────────
    for i in range(n_frames):
        frame = signal[i * frame_samples:(i + 1) * frame_samples]
        if rms_db(frame) > threshold:
            return i * frame_samples

    return 0  # si no encuentra onset, devuelve el inicio

def procesar():
    entrada = Path(CARPETA_ENTRADA)
    salida  = Path(CARPETA_SALIDA)

    wavs = sorted(entrada.rglob('*.wav'))
    if not wavs:
        print(f"No se encontraron WAVs en {entrada} ni sus subcarpetas")
        return

    print(f"Procesando {len(wavs)} archivos...\n")

    # ── Paso 1: detectar onset en cada archivo ─────────────────────────────
    onsets     = {}
    duraciones = {}
    samplerate = None

    for wav in wavs:
        rel    = wav.relative_to(entrada)
        signal, sr = sf.read(str(wav), dtype='float32')
        if signal.ndim > 1:
            signal = signal[:, 0]

        if samplerate is None:
            samplerate = sr
        elif sr != samplerate:
            print(f"  [ADVERTENCIA] {rel} tiene sr={sr}, esperado {samplerate}")

        onset_idx   = detectar_onset(signal, sr)
        pre_samples = int(sr * PRE_ONSET_MS / 1000)
        start_idx   = max(0, onset_idx - pre_samples)

        onsets[rel]     = start_idx
        duraciones[rel] = len(signal) - start_idx

        print(f"  {str(rel):<48}  piso estimado con 3s  |  onset: {onset_idx/sr:.3f}s  →  recorte: {start_idx/sr:.3f}s")

    # ── Paso 2: duración común = la más corta ─────────────────────────────
    dur_comun = min(duraciones.values())
    dur_seg   = dur_comun / samplerate
    print(f"\nDuración común: {dur_seg:.3f} s ({dur_comun} muestras)\n")

    # ── Paso 3: recortar y guardar manteniendo estructura ─────────────────
    for wav in wavs:
        rel    = wav.relative_to(entrada)
        signal, sr = sf.read(str(wav), dtype='float32')
        if signal.ndim > 1:
            signal = signal[:, 0]

        start     = onsets[rel]
        recortado = signal[start:start + dur_comun]

        destino = salida / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(destino), recortado, sr, subtype='PCM_24')
        print(f"  [ok] {str(rel):<48}  ({len(recortado)/sr:.3f} s)")

    print(f"\n── Listo ─────────────────────────────────────────")
    print(f"  Archivos en:    {salida}")
    print(f"  Duración final: {dur_seg:.3f} s")
    print(f"  Sample rate:    {samplerate} Hz")

if __name__ == '__main__':
    procesar()