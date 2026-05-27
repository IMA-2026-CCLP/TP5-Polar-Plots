"""
interpolar_mic9_spline.py
═════════════════════════
Genera los WAVs del micrófono 9 (canal faltante) interpolando
la magnitud espectral en función del ángulo usando spline cúbica,
siguiendo el criterio del estándar CTA-2034-A.

Usa STFT con overlap-add para evitar artefactos de shimmer que
aparecen cuando se hace la interpolación sobre la señal completa
de una sola vez (la FFT global asume periodicidad, lo que genera
convolución circular y distorsión audible).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MÉTODO: STFT + SPLINE + OVERLAP-ADD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Para cada frame temporal:

  1. Extraer un frame corto de cada micrófono (ej. 2048 muestras).
  2. Aplicar ventana Hann → elimina discontinuidades en los bordes.
  3. FFT de cada frame ventaneado.
  4. Para cada bin de frecuencia:
       a. Magnitud  → spline cúbica sobre los 18 ángulos disponibles
                      → evaluar en 80° (CTA-2034-A)
       b. Fase      → interpolación lineal entre mic 8 (70°) y mic 10 (90°)
                      usando fase desenrollada para evitar saltos de 2π
  5. Reconstruir espectro complejo: H9 = mag_interp * exp(j * fase_interp)
  6. IFFT → frame temporal interpolado → aplicar ventana de síntesis
  7. Overlap-add: acumular frames solapados en la señal de salida.

Por qué STFT soluciona el shimmer:
  - Cada frame es corto y ventaneado → no hay discontinuidades
  - La convolución circular es inocua dentro de un frame corto
  - El overlap-add reconstruye la señal completa correctamente
  - La ventana Hann con 75% de solapamiento garantiza COLA
    (Constant Overlap-Add): suma de ventanas = 1 en todo momento

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ESTRUCTURA DE CARPETAS ESPERADA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
forte/
  mic1/   mic_1_ang_forte_0.wav
          mic_1_ang_forte_10.wav  ...
  mic8/   mic_8_ang_forte_0.wav   ← vecino izquierdo del hueco (70°)
  mic9/   ← se genera aquí
  mic10/  mic_10_ang_forte_0.wav  ← vecino derecho del hueco (90°)
  mic19/  ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIERE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  pip install numpy soundfile scipy
"""

import numpy as np
import soundfile as sf
from scipy.interpolate import CubicSpline
from pathlib import Path
import re

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN — editá solo esta sección
# ══════════════════════════════════════════════════════════════

CARPETA_ENTRADA = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_processed\forte"

DINAMICA        = "forte"

MIC_FALTANTE    = 9        # número de micrófono a generar
ANGULO_FALTANTE = 80.0     # ángulo en grados del mic faltante

# Ángulos de todos los micrófonos del array (0° a 180°, equiespaciados 10°)
ANGULOS_ARRAY = np.arange(0, 190, 10, dtype=float)  # [0, 10, 20, ..., 180]

# Micrófonos vecinos inmediatos del hueco (solo para interpolación de fase)
MIC_VEC_IZQ = 8   # → 70°
MIC_VEC_DER = 10  # → 90°

# ── Parámetros STFT ───────────────────────────────────────────────────────────
# Frame size: compromiso entre resolución temporal y frecuencial
#   2048 muestras a 48kHz → 42.7 ms por frame, Δf = 23.4 Hz
#   4096 muestras a 48kHz → 85.3 ms por frame, Δf = 11.7 Hz
# Para voz cantada (F4–F5, 350–700 Hz), 4096 da buena resolución frecuencial
FRAME_SIZE  = 8192    # muestras por frame (potencia de 2)

# Solapamiento: 75% es el estándar para ventana Hann con COLA garantizado
# HOP = FRAME_SIZE // 4 → 75% overlap
HOP_SIZE    = FRAME_SIZE // 4

# ══════════════════════════════════════════════════════════════

PATRON = re.compile(r'mic_(\d+)_ang_(\w+)_(\d+)\.wav', re.IGNORECASE)


def cargar_mono(path: Path):
    """Carga un WAV y lo convierte a mono float32."""
    sig, sr = sf.read(str(path), dtype='float32')
    if sig.ndim > 1:
        sig = sig[:, 0]
    return sig, sr


def interpolar_frame(espectros_frame: dict,
                     angulos_disp: np.ndarray,
                     angulo_obj: float,
                     ang_izq: float,
                     ang_der: float):
    """
    Interpola el espectro complejo de un único frame en angulo_obj.

    Parámetros:
        espectros_frame : dict {angulo_mic: espectro_complejo (n_bins,)}
        angulos_disp    : array de ángulos disponibles (sin el faltante)
        angulo_obj      : ángulo a interpolar (80.0°)
        ang_izq / ang_der : ángulos de los vecinos para la fase

    Retorna:
        espectro_interp : np.ndarray complejo interpolado
    """
    # ── Magnitud: spline cúbica sobre todos los ángulos ───────────────────
    # Shape magnitudes: (n_angulos, n_bins)
    magnitudes = np.array([np.abs(espectros_frame[a]) for a in angulos_disp])

    # CubicSpline vectorizada: interpola cada bin de frecuencia por separado
    # bc_type='not-a-knot': condición de frontera estándar, no asume
    # periodicidad en el eje angular (correcto para 0°–180°)
    cs = CubicSpline(angulos_disp, magnitudes, axis=0, bc_type='not-a-knot')
    mag_interp = np.maximum(cs(angulo_obj), 0.0)  # magnitud ≥ 0

    # ── Fase: interpolación lineal entre vecinos con unwrap ───────────────
    fase_izq = np.angle(espectros_frame[ang_izq])
    fase_der = np.angle(espectros_frame[ang_der])

    # Desenrollar sobre el eje de frecuencias para evitar saltos de ±2π
    fases = np.unwrap(np.stack([fase_izq, fase_der], axis=0), axis=1)

    # t = 0.5 porque el ángulo faltante (80°) es equidistante entre 70° y 90°
    t = (angulo_obj - ang_izq) / (ang_der - ang_izq)
    fase_interp = (1 - t) * fases[0] + t * fases[1]

    return (mag_interp * np.exp(1j * fase_interp)).astype(np.complex64)


def stft_interpolar(senales: dict,
                    angulos_disp: np.ndarray,
                    angulo_obj: float,
                    ang_izq: float,
                    ang_der: float,
                    largo: int,
                    frame_size: int,
                    hop_size: int):
    """
    Procesa la señal completa frame a frame via STFT + overlap-add.

    Para cada frame:
      1. Extraer + ventana Hann (análisis)
      2. FFT
      3. Interpolación espectral (spline magnitud + lineal fase)
      4. IFFT
      5. Ventana Hann (síntesis) + overlap-add

    La ventana Hann con hop = frame/4 (75% overlap) cumple COLA:
      suma de ventanas cuadradas = constante → reconstrucción perfecta.

    Retorna:
        señal interpolada de longitud `largo`
    """
    ventana = np.hanning(frame_size).astype(np.float32)

    # Buffer de salida con margen para el último frame
    n_salida = largo + frame_size
    salida   = np.zeros(n_salida, dtype=np.float64)
    # Buffer para acumular el cuadrado de la ventana (normalización COLA)
    ventana_acum = np.zeros(n_salida, dtype=np.float64)

    # Rellenar señales con ceros para cubrir el último frame incompleto
    senales_pad = {
        ang: np.pad(sig, (0, frame_size)) for ang, sig in senales.items()
    }

    n_frames = (largo - 1) // hop_size + 1

    for i in range(n_frames):
        inicio = i * hop_size
        fin    = inicio + frame_size

        # ── 1 & 2. Extraer frame y aplicar ventana Hann + FFT ─────────────
        espectros_frame = {}
        for ang in angulos_disp:
            frame = senales_pad[ang][inicio:fin]
            if len(frame) < frame_size:
                frame = np.pad(frame, (0, frame_size - len(frame)))
            espectros_frame[ang] = np.fft.rfft(frame * ventana)

        # ── 3. Interpolación espectral ─────────────────────────────────────
        espectro_interp = interpolar_frame(
            espectros_frame, angulos_disp, angulo_obj, ang_izq, ang_der
        )

        # ── 4. IFFT ───────────────────────────────────────────────────────
        frame_out = np.fft.irfft(espectro_interp, n=frame_size).real

        # ── 5. Ventana de síntesis + overlap-add ──────────────────────────
        salida[inicio:fin]      += frame_out * ventana
        ventana_acum[inicio:fin] += ventana ** 2

    # Normalizar por la acumulación de ventanas (COLA)
    # Evitar división por cero en los extremos con relleno de ceros
    ventana_acum = np.maximum(ventana_acum, 1e-8)
    salida /= ventana_acum

    return salida[:largo].astype(np.float32)


def procesar():
    entrada = Path(CARPETA_ENTRADA)

    # ── Descubrir todos los WAVs por (ángulo_fuente, mic_num) ─────────────
    archivos = {}  # archivos[ang_fuente][mic_num] = Path

    for wav in sorted(entrada.rglob('*.wav')):
        m = PATRON.match(wav.name)
        if not m:
            continue
        mic_num  = int(m.group(1))
        dinamica = m.group(2).lower()
        ang      = int(m.group(3))

        if dinamica != DINAMICA or mic_num == MIC_FALTANTE:
            continue
        archivos.setdefault(ang, {})[mic_num] = wav

    angulos_medicion = sorted(archivos.keys())
    if not angulos_medicion:
        print(f"No se encontraron archivos para dinámica '{DINAMICA}'")
        return

    print(f"Ángulos de medición: {angulos_medicion}")
    print(f"Frame: {FRAME_SIZE} muestras  |  Hop: {HOP_SIZE} ({100*(1-HOP_SIZE/FRAME_SIZE):.0f}% overlap)\n")

    salida_dir = entrada / f"mic{MIC_FALTANTE}"
    salida_dir.mkdir(exist_ok=True)

    # Ángulos de los vecinos para la fase
    ang_izq = ANGULOS_ARRAY[MIC_VEC_IZQ - 1]  # 70.0°
    ang_der = ANGULOS_ARRAY[MIC_VEC_DER - 1]  # 90.0°

    for ang_fuente in angulos_medicion:
        mics_disp = archivos[ang_fuente]

        if MIC_VEC_IZQ not in mics_disp or MIC_VEC_DER not in mics_disp:
            print(f"  [SKIP] ángulo {ang_fuente}°: falta mic_{MIC_VEC_IZQ} o mic_{MIC_VEC_DER}")
            continue

        # ── Cargar señales ─────────────────────────────────────────────────
        senales   = {}   # ang_mic -> señal float32
        sr_comun  = None
        largo_min = None

        for mic_num, wav_path in sorted(mics_disp.items()):
            sig, sr = cargar_mono(wav_path)

            if sr_comun is None:
                sr_comun = sr
            elif sr != sr_comun:
                print(f"  [WARN] mic_{mic_num} sr={sr} ≠ {sr_comun}, saltando")
                continue

            largo_min = min(largo_min, len(sig)) if largo_min else len(sig)
            senales[ANGULOS_ARRAY[mic_num - 1]] = sig

        # Recortar todas las señales al mismo largo
        senales = {ang: sig[:largo_min] for ang, sig in senales.items()}

        angulos_disp = np.array(sorted(senales.keys()))

        dur_s = largo_min / sr_comun
        print(f"  ángulo fuente {ang_fuente:>4}°  |  {len(angulos_disp)} mics  "
              f"|  {dur_s:.2f} s  |  procesando...", end=' ', flush=True)

        # ── STFT + interpolación + overlap-add ────────────────────────────
        sig_mic9 = stft_interpolar(
            senales      = senales,
            angulos_disp = angulos_disp,
            angulo_obj   = ANGULO_FALTANTE,
            ang_izq      = ang_izq,
            ang_der      = ang_der,
            largo        = largo_min,
            frame_size   = FRAME_SIZE,
            hop_size     = HOP_SIZE
        )

        # Normalizar si hay clipping
        pico = np.max(np.abs(sig_mic9))
        if pico > 1.0:
            print(f"[CLIP pico={pico:.3f}]", end=' ')
            sig_mic9 /= pico

        # ── Guardar ───────────────────────────────────────────────────────
        nombre  = f"mic_{MIC_FALTANTE}_ang_{DINAMICA}_{ang_fuente}.wav"
        destino = salida_dir / nombre
        sf.write(str(destino), sig_mic9, sr_comun, subtype='PCM_24')
        print(f"→ {nombre}")

    print(f"\n── Listo ──────────────────────────────────────────────")
    print(f"  Archivos en: {salida_dir}")
    print(f"  Frame size:  {FRAME_SIZE} muestras = {FRAME_SIZE/sr_comun*1000:.1f} ms a {sr_comun} Hz")
    print(f"  Δf:          {sr_comun/FRAME_SIZE:.2f} Hz/bin")

if __name__ == '__main__':
    procesar()