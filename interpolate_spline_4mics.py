"""
interpolar_mic9_spline_4pts.py
══════════════════════════════
Genera los WAVs del micrófono 9 interpolando con spline cúbica
usando 4 puntos de soporte: mic 7 (60°), mic 8 (70°), mic 10 (90°)
y mic 11 (100°).

Con 4 puntos la spline cúbica tiene curvatura real — no degenera
en interpolación lineal como ocurre con solo 2 puntos.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MÉTODO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Para cada frame STFT:
  1. FFT de mic 7, 8, 10 y 11 (ventana Hann)
  2. Magnitud en escala lineal de los 4 espectros
  3. Spline cúbica sobre los 4 ángulos [60°, 70°, 90°, 100°]
     → evaluar en 80°
  4. Fase: interpolación lineal con unwrap entre mic 8 y mic 10
     (los vecinos inmediatos del hueco)
  5. Reconstruir espectro: mag * exp(j * fase)
  6. IFFT + overlap-add (ventana Hann, 75% overlap, COLA)

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
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

CARPETA_ENTRADA = r"D:\UNTREF\IMA\TP5 - PATRON POLAR\Medición_Juli\Media_processed\forte"

DINAMICA        = "forte"

MIC_FALTANTE    = 9      # micrófono a generar
ANGULO_FALTANTE = 80.0   # ángulo en grados del mic faltante

# Los 4 micrófonos de soporte para la spline
# mic_num → ángulo en el array
MICS_SOPORTE = {
    7:  60.0,   # izquierdo externo
    8:  70.0,   # izquierdo interno  ← vecino inmediato del hueco
    10: 90.0,   # derecho interno    ← vecino inmediato del hueco
    11: 100.0,  # derecho externo
}

# Vecinos inmediatos (para la interpolación de fase)
MIC_FASE_IZQ = 8
MIC_FASE_DER = 10

FRAME_SIZE = 8192             # muestras por frame (~85 ms a 48kHz)
HOP_SIZE   = FRAME_SIZE // 4  # 75% overlap, COLA garantizado con Hann

# ══════════════════════════════════════════════════════════════

PATRON = re.compile(r'mic_(\d+)_ang_(\w+)_(\d+)\.wav', re.IGNORECASE)

# Arrays ordenados por ángulo para la spline
ANGULOS_SOPORTE = np.array(sorted(MICS_SOPORTE.values()))   # [60, 70, 90, 100]
MICS_ORDENADOS  = sorted(MICS_SOPORTE, key=MICS_SOPORTE.get) # [7, 8, 10, 11]


def cargar_mono(path: Path):
    """Carga un WAV y lo convierte a mono float32."""
    sig, sr = sf.read(str(path), dtype='float32')
    if sig.ndim > 1:
        sig = sig[:, 0]
    return sig, sr


def interpolar_frame(espectros: dict, t_interp: float) -> np.ndarray:
    """
    Interpola el espectro complejo en ANGULO_FALTANTE usando
    spline cúbica sobre 4 puntos de soporte.

    Parámetros:
        espectros : dict {angulo: espectro_complejo (n_bins,)}
                    debe contener exactamente los 4 ángulos de soporte
        t_interp  : peso de fase entre vecinos inmediatos [0=izq, 1=der]

    Retorna:
        espectro complejo interpolado (n_bins,)
    """
    # ── Magnitud: spline cúbica sobre 4 puntos ────────────────────────────
    # magnitudes shape: (4, n_bins)
    magnitudes = np.array([np.abs(espectros[a]) for a in ANGULOS_SOPORTE])

    # CubicSpline con 4 puntos → curvatura real, no degenera en lineal
    # axis=0: la spline varía a lo largo de los ángulos (filas),
    #         interpolando cada bin de frecuencia (columna) por separado
    # bc_type='not-a-knot': condición estándar, no impone restricciones
    #                        artificiales en los extremos
    cs = CubicSpline(ANGULOS_SOPORTE, magnitudes, axis=0, bc_type='not-a-knot')
    mag_interp = np.maximum(cs(ANGULO_FALTANTE), 0.0)  # magnitud ≥ 0

    # ── Fase: interpolación lineal con unwrap entre vecinos inmediatos ────
    # Usamos solo mic 8 y mic 10 para la fase porque son los más cercanos
    # al ángulo objetivo. Incorporar mic 7 y 11 en la fase con spline
    # introduce inestabilidades por aliasing espacial a altas frecuencias.
    ang_izq  = MICS_SOPORTE[MIC_FASE_IZQ]   # 70°
    ang_der  = MICS_SOPORTE[MIC_FASE_DER]   # 90°
    fase_izq = np.angle(espectros[ang_izq])
    fase_der = np.angle(espectros[ang_der])

    # Desenrollar la fase para evitar saltos de ±2π antes de interpolar
    fases       = np.unwrap(np.stack([fase_izq, fase_der], axis=0), axis=1)
    fase_interp = (1 - t_interp) * fases[0] + t_interp * fases[1]

    return (mag_interp * np.exp(1j * fase_interp)).astype(np.complex64)


def stft_interpolar(senales: dict,
                    t_interp: float,
                    largo: int,
                    frame_size: int,
                    hop_size: int) -> np.ndarray:
    """
    Procesa la señal completa frame a frame via STFT + overlap-add.

    Parámetros:
        senales   : dict {angulo: señal float32} con los 4 mics de soporte
        t_interp  : peso de interpolación de fase (0.5 para mic equidistante)
        largo     : duración en muestras de la señal de salida
        frame_size: muestras por frame (potencia de 2)
        hop_size  : salto entre frames (frame_size // 4 para 75% overlap)

    Retorna:
        señal interpolada float32 de longitud `largo`
    """
    ventana = np.hanning(frame_size).astype(np.float32)

    n_salida     = largo + frame_size
    salida       = np.zeros(n_salida, dtype=np.float64)
    ventana_acum = np.zeros(n_salida, dtype=np.float64)

    # Zero-pad todas las señales para cubrir el último frame incompleto
    senales_pad = {
        ang: np.pad(sig, (0, frame_size)) for ang, sig in senales.items()
    }

    n_frames = (largo - 1) // hop_size + 1

    for i in range(n_frames):
        inicio = i * hop_size
        fin    = inicio + frame_size

        # ── FFT de cada mic de soporte con ventana Hann ───────────────────
        espectros_frame = {}
        for ang in ANGULOS_SOPORTE:
            frame = senales_pad[ang][inicio:fin]
            if len(frame) < frame_size:
                frame = np.pad(frame, (0, frame_size - len(frame)))
            espectros_frame[ang] = np.fft.rfft(frame * ventana)

        # ── Spline cúbica en magnitud + lineal en fase ────────────────────
        esp_interp = interpolar_frame(espectros_frame, t_interp)

        # ── IFFT + ventana de síntesis + overlap-add ──────────────────────
        frame_out = np.fft.irfft(esp_interp, n=frame_size).real
        salida[inicio:fin]       += frame_out * ventana
        ventana_acum[inicio:fin] += ventana ** 2

    # Normalizar por acumulación de ventanas (COLA)
    salida /= np.maximum(ventana_acum, 1e-8)

    return salida[:largo].astype(np.float32)


def procesar():
    entrada = Path(CARPETA_ENTRADA)

    # ── Descubrir archivos de los 4 mics de soporte por ángulo de fuente ─
    # archivos[ang_fuente][mic_num] = Path
    archivos = {}

    for wav in sorted(entrada.rglob('*.wav')):
        m = PATRON.match(wav.name)
        if not m:
            continue
        mic_num  = int(m.group(1))
        dinamica = m.group(2).lower()
        ang      = int(m.group(3))

        if dinamica != DINAMICA or mic_num not in MICS_SOPORTE:
            continue
        archivos.setdefault(ang, {})[mic_num] = wav

    # Solo procesar ángulos donde estén los 4 mics de soporte
    angulos = sorted(
        ang for ang, mics in archivos.items()
        if all(m in mics for m in MICS_SOPORTE)
    )

    if not angulos:
        print(f"No se encontraron ángulos con los 4 mics de soporte "
              f"({list(MICS_SOPORTE.keys())}) para dinámica '{DINAMICA}'")
        return

    # Peso de interpolación de fase: equidistante → t = 0.5
    t_interp = (ANGULO_FALTANTE - MICS_SOPORTE[MIC_FASE_IZQ]) / \
               (MICS_SOPORTE[MIC_FASE_DER] - MICS_SOPORTE[MIC_FASE_IZQ])

    print(f"Mics de soporte: {MICS_ORDENADOS} → ángulos {ANGULOS_SOPORTE}°")
    print(f"Objetivo:        mic_{MIC_FALTANTE} en {ANGULO_FALTANTE}°  [t fase={t_interp}]")
    print(f"Ángulos de fuente a procesar: {angulos}")
    print(f"Frame: {FRAME_SIZE} muestras | Hop: {HOP_SIZE} "
          f"({100*(1-HOP_SIZE/FRAME_SIZE):.0f}% overlap)\n")

    salida_dir = entrada / f"mic{MIC_FALTANTE}"
    salida_dir.mkdir(exist_ok=True)

    for ang_fuente in angulos:
        # ── Cargar los 4 mics de soporte ──────────────────────────────────
        senales   = {}
        sr_comun  = None
        largo_min = None

        for mic_num in MICS_ORDENADOS:
            sig, sr = cargar_mono(archivos[ang_fuente][mic_num])

            if sr_comun is None:
                sr_comun = sr
            elif sr != sr_comun:
                print(f"  [WARN] mic_{mic_num} sr={sr}≠{sr_comun}, saltando ángulo")
                break

            largo_min = min(largo_min, len(sig)) if largo_min else len(sig)
            senales[MICS_SOPORTE[mic_num]] = sig   # clave = ángulo

        if len(senales) < 4:
            print(f"  [SKIP] {ang_fuente}°: no se pudieron cargar los 4 mics")
            continue

        # Recortar todas al mismo largo
        senales = {ang: sig[:largo_min] for ang, sig in senales.items()}

        print(f"  {ang_fuente:>4}°  |  {largo_min/sr_comun:.2f} s  |  "
              f"procesando...", end=' ', flush=True)

        sig_mic9 = stft_interpolar(
            senales    = senales,
            t_interp   = t_interp,
            largo      = largo_min,
            frame_size = FRAME_SIZE,
            hop_size   = HOP_SIZE
        )

        pico = np.max(np.abs(sig_mic9))
        if pico > 1.0:
            print(f"[clip={pico:.2f}] ", end='')
            sig_mic9 /= pico

        nombre  = f"mic_{MIC_FALTANTE}_ang_{DINAMICA}_{ang_fuente}.wav"
        destino = salida_dir / nombre
        sf.write(str(destino), sig_mic9, sr_comun, subtype='PCM_24')
        print(f"→ {nombre}")

    print(f"\n── Listo ──────────────────────────────────────────────────")
    print(f"  Archivos en: {salida_dir}")
    print(f"  Δf por bin:  {sr_comun / FRAME_SIZE:.2f} Hz  "
          f"(frame={FRAME_SIZE}, sr={sr_comun} Hz)")

if __name__ == '__main__':
    procesar()