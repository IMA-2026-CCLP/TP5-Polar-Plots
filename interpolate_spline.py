"""
interpolar_mic9_spline.py
═════════════════════════
Genera los WAVs del micrófono 9 (canal faltante) interpolando
la magnitud espectral en función del ángulo usando spline cúbica,
siguiendo el criterio del estándar CTA-2034-A.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MÉTODO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Para cada bin de frecuencia f:

  1. Se calcula la FFT de cada micrófono disponible (1–8 y 10–19).
  2. Se extrae la magnitud espectral |H(mic_k, f)| para cada ángulo θ_k.
  3. Se ajusta una spline cúbica sobre (θ_k, |H(θ_k, f)|).
  4. Se evalúa la spline en θ = 80° → magnitud interpolada del mic 9.
  5. Para la fase se usa interpolación lineal entre mic 8 (70°) y mic 10 (90°),
     trabajando sobre la fase desenrollada (unwrapped) para evitar saltos de 2π.
  6. Se reconstruye el espectro complejo: H9(f) = magnitud * exp(j * fase).
  7. IFFT → señal temporal del mic 9 interpolado.

Por qué magnitud con spline y fase con interpolación lineal:
  - La magnitud varía suavemente con el ángulo → spline cúbica es ideal.
  - La fase es más sensible a pequeñas variaciones espaciales y puede
    tener discontinuidades incluso después del unwrap cuando se usan
    muchos puntos; interpolación lineal entre vecinos inmediatos es
    más estable y suficientemente precisa para un ángulo equidistante.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ESTRUCTURA DE CARPETAS ESPERADA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
forte/
  mic1/   mic_1_ang_forte_0.wav
          mic_1_ang_forte_10.wav
          ...
  mic2/   mic_2_ang_forte_0.wav
          ...
  mic8/   mic_8_ang_forte_0.wav   ← vecino izquierdo del hueco
          ...
  mic9/   ← (no existe o está vacío, se genera aquí)
  mic10/  mic_10_ang_forte_0.wav  ← vecino derecho del hueco
          ...
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

DINAMICA        = "forte"   # dinámica a procesar

MIC_FALTANTE    = 9         # número de micrófono a generar
ANGULO_FALTANTE = 80.0      # ángulo en grados del mic faltante

# Ángulos de todos los micrófonos del array (0° a 180°, equiespaciados 10°)
# El ángulo del mic faltante (80°) se excluye automáticamente
ANGULOS_ARRAY = np.arange(0, 190, 10, dtype=float)   # [0, 10, 20, ..., 180]

# Micrófonos vecinos inmediatos (usados solo para la interpolación de fase)
MIC_VEC_IZQ = 8    # mic a la izquierda del hueco  → 70°
MIC_VEC_DER = 10   # mic a la derecha del hueco    → 90°

#  N_FFT se calcula dinámicamente por señal (ver abajo)




# ══════════════════════════════════════════════════════════════

PATRON = re.compile(r'mic_(\d+)_ang_(\w+)_(\d+)\.wav', re.IGNORECASE)


def next_pow2(n: int) -> int:
    """Devuelve la potencia de 2 más cercana mayor o igual a n."""
    return int(2 ** np.ceil(np.log2(n))) if n > 1 else 1


def cargar_mono(path: Path):
    """Carga un WAV y lo convierte a mono float32 si es multicanal."""
    sig, sr = sf.read(str(path), dtype='float32')
    if sig.ndim > 1:
        sig = sig[:, 0]
    return sig, sr


def calcular_espectro(signal: np.ndarray, n_fft: int):
    """
    Calcula la FFT de una señal con zero-padding a n_fft muestras.

    n_fft se pasa desde afuera y es siempre la siguiente potencia de 2
    al largo real de la señal más larga del grupo → sin truncamiento.

    Retorna:
        espectro : np.ndarray complejo, longitud n_fft // 2 + 1
                   (solo la mitad positiva del espectro, señal real)
    """
    return np.fft.rfft(signal, n=n_fft)


def interpolar_angulo(angulos: np.ndarray,
                      espectros: dict,
                      angulo_objetivo: float,
                      mic_izq: int,
                      mic_der: int,
                      angulos_array: np.ndarray,
                      n_fft: int,
                      sr: int):
    """
    Interpola el espectro complejo en angulo_objetivo usando:
      - Spline cúbica sobre la MAGNITUD en función del ángulo (todos los mics)
      - Interpolación lineal sobre la FASE desenrollada (solo vecinos inmediatos)

    Parámetros:
        angulos      : array de ángulos disponibles (sin el faltante)
        espectros    : dict {angulo: espectro_complejo}
        angulo_objetivo : ángulo a interpolar (80.0°)
        mic_izq / mic_der : índices de los micrófonos vecinos en angulos_array
        n_fft        : tamaño de la FFT
        sr           : sample rate

    Retorna:
        espectro_interp : np.ndarray complejo interpolado en angulo_objetivo
    """
    n_bins = n_fft // 2 + 1

    # ── Magnitudes para cada ángulo disponible ────────────────────────────
    # Shape: (n_angulos, n_bins)
    magnitudes = np.array([np.abs(espectros[a]) for a in angulos])

    # ── Spline cúbica sobre la magnitud bin a bin ─────────────────────────
    # CubicSpline interpola a través de todos los puntos angulares
    # para cada bin de frecuencia de forma vectorizada.
    #
    # Nota: axis=0 indica que la spline varía a lo largo de los ángulos
    # (filas), interpolando cada columna (bin de frecuencia) por separado.
    cs = CubicSpline(angulos, magnitudes, axis=0, bc_type='not-a-knot')
    mag_interp = cs(angulo_objetivo)           # shape: (n_bins,)
    mag_interp = np.maximum(mag_interp, 0.0)  # magnitud no puede ser negativa

    # ── Fase: interpolación lineal entre vecinos inmediatos ───────────────
    ang_izq = angulos_array[mic_izq - 1]   # ángulo del mic vecino izquierdo
    ang_der = angulos_array[mic_der - 1]   # ángulo del mic vecino derecho

    fase_izq = np.angle(espectros[ang_izq])
    fase_der = np.angle(espectros[ang_der])

    # Desenrollar la fase para evitar saltos de ±2π en la interpolación
    # np.unwrap trabaja sobre el eje de frecuencias (axis=0 por defecto)
    fases_apiladas = np.unwrap(np.stack([fase_izq, fase_der], axis=0), axis=0)
    fase_izq_u = fases_apiladas[0]
    fase_der_u = fases_apiladas[1]

    # Peso de interpolación lineal: dónde cae angulo_objetivo entre izq y der
    t = (angulo_objetivo - ang_izq) / (ang_der - ang_izq)
    fase_interp = (1 - t) * fase_izq_u + t * fase_der_u

    # ── Reconstruir espectro complejo: magnitud * e^(j*fase) ──────────────
    espectro_interp = mag_interp * np.exp(1j * fase_interp)

    return espectro_interp.astype(np.complex64)


def procesar():
    entrada = Path(CARPETA_ENTRADA)

    # ── Descubrir todos los WAVs organizados por (mic, ángulo) ───────────
    # archivos[angulo][mic_num] = Path
    archivos = {}

    for wav in sorted(entrada.rglob('*.wav')):
        m = PATRON.match(wav.name)
        if not m:
            continue
        mic_num  = int(m.group(1))
        dinamica = m.group(2).lower()
        angulo   = int(m.group(3))

        if dinamica != DINAMICA:
            continue
        if mic_num == MIC_FALTANTE:
            continue   # ignorar archivos del mic faltante si existieran

        archivos.setdefault(angulo, {})[mic_num] = wav

    angulos_medicion = sorted(archivos.keys())
    if not angulos_medicion:
        print(f"No se encontraron archivos para dinámica '{DINAMICA}'")
        return

    print(f"Ángulos de medición encontrados: {angulos_medicion}")
    print(f"Generando mic_{MIC_FALTANTE} (ángulo fuente {ANGULO_FALTANTE}°) "
          f"para cada uno...\n")

    # ── Crear carpeta de salida para mic9 ─────────────────────────────────
    salida_dir = entrada / f"mic{MIC_FALTANTE}"
    salida_dir.mkdir(exist_ok=True)

    for ang_fuente in angulos_medicion:
        mics_disponibles = archivos[ang_fuente]

        # Verificar que tengamos los vecinos inmediatos como mínimo
        if MIC_VEC_IZQ not in mics_disponibles or MIC_VEC_DER not in mics_disponibles:
            print(f"  [SKIP] ángulo {ang_fuente}°: faltan mic_{MIC_VEC_IZQ} "
                  f"o mic_{MIC_VEC_DER}")
            continue

        # ── Cargar todos los micrófonos disponibles ────────────────────────
        espectros  = {}   # angulo_mic -> espectro complejo
        sr_comun   = None
        largo_min  = None

        for mic_num, wav_path in sorted(mics_disponibles.items()):
            sig, sr = cargar_mono(wav_path)

            if sr_comun is None:
                sr_comun = sr
            elif sr != sr_comun:
                print(f"  [ADVERTENCIA] mic_{mic_num} ang={ang_fuente}° "
                      f"tiene sr={sr}, se esperaba {sr_comun}. Saltando.")
                continue

            largo_min = min(largo_min, len(sig)) if largo_min else len(sig)

            # Guardamos la señal temporalmente; calculamos la FFT después
            # de conocer largo_min para que n_fft sea consistente entre mics
            espectros[ANGULOS_ARRAY[mic_num - 1]] = sig

        # ── N_FFT dinámico: siguiente potencia de 2 al largo real ───────────
        # Esto garantiza que la FFT cubre toda la señal sin truncarla.
        # Δf = sr / n_fft  (resolución frecuencial resultante)
        n_fft = next_pow2(largo_min)
        df    = sr_comun / n_fft
        print(f"         n_fft={n_fft} ({largo_min/sr_comun:.2f}s)  Δf={df:.3f} Hz/bin")

        # ── Convertir señales guardadas a espectros con n_fft común ─────────
        espectros_fft = {
            ang: calcular_espectro(sig[:largo_min], n_fft)
            for ang, sig in espectros.items()
        }

        # Ángulos del array para los que tenemos espectro (excluye el faltante)
        angulos_disponibles = np.array(sorted(espectros_fft.keys()))

        # ── Interpolar espectro en el ángulo del mic faltante ─────────────
        espectro_mic9 = interpolar_angulo(
            angulos         = angulos_disponibles,
            espectros       = espectros_fft,
            angulo_objetivo = ANGULO_FALTANTE,
            mic_izq         = MIC_VEC_IZQ,
            mic_der         = MIC_VEC_DER,
            angulos_array   = ANGULOS_ARRAY,
            n_fft           = n_fft,
            sr              = sr_comun
        )

        # ── IFFT → señal temporal ──────────────────────────────────────────
        # irfft devuelve n_fft muestras; recortamos al largo_min original
        # (el zero-padding de la FFT no agrega información real)
        sig_mic9 = np.fft.irfft(espectro_mic9, n=n_fft)[:largo_min]
        sig_mic9 = sig_mic9.astype(np.float32)

        # Normalizar si hay clipping (no debería ocurrir, pero por seguridad)
        pico = np.max(np.abs(sig_mic9))
        if pico > 1.0:
            print(f"  [CLIP] ángulo {ang_fuente}°: pico = {pico:.3f}, normalizando")
            sig_mic9 /= pico

        # ── Guardar ───────────────────────────────────────────────────────
        nombre  = f"mic_{MIC_FALTANTE}_ang_{DINAMICA}_{ang_fuente}.wav"
        destino = salida_dir / nombre
        sf.write(str(destino), sig_mic9, sr_comun, subtype='PCM_24')

        n_mics_usados = len(angulos_disponibles)
        print(f"  [ok] ángulo fuente {ang_fuente:>4}°  |  "
              f"{n_mics_usados} mics usados en spline  |  → {nombre}")

    print(f"\n── Listo ──────────────────────────────────────────────────")
    print(f"  Archivos generados en: {salida_dir}")
    print(f"  Sample rate: {sr_comun} Hz")

if __name__ == '__main__':
    procesar()