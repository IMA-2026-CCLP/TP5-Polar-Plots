# -*- coding: utf-8 -*-
"""
Procesamiento digital de señal:
  - FiltroPasaAltos     (Butterworth IIR, sosfiltfilt — fase cero, O(N))
  - AlineadorGCCPHAT    (cross-correlación con blanqueo de fase)
  - DetectorOnsetOffset (umbral adaptivo sobre mic de referencia)
"""

import numpy as np
from scipy.signal import butter, sosfiltfilt


# ═══════════════════════════════════════════════════════════════
# Filtro pasa altos
# ═══════════════════════════════════════════════════════════════

class FiltroPasaAltosFIR:
    """
    Pasa altos Butterworth de orden 4, fase cero (sosfiltfilt).

    Nombre heredado por compatibilidad con el pipeline; internamente
    usa IIR en formato SOS, que es ~100× más rápido que el FIR Kaiser
    de orden ~4000 que requeriría la misma fc a 44.1 kHz.

    sosfiltfilt aplica el filtro dos veces (ida+vuelta) → delay neto = 0,
    respuesta en magnitud equivalente a orden 8 Butterworth.
    """

    ORDEN = 4

    def __init__(self, fc_hz: float, ripple_db: float = 60.0, width_hz: float = 40.0):
        self.fc_hz = fc_hz
        self._sos  = None
        self._sr   = None

    def preparar(self, sr: int):
        """Diseña el filtro SOS para el SR dado. Devuelve (orden_efectivo, 0.0)."""
        fc_norm  = self.fc_hz / (sr / 2.0)
        self._sos = butter(self.ORDEN, fc_norm, btype="high", output="sos")
        self._sr  = sr
        return self.ORDEN * 2, 0.0   # ×2 porque sosfiltfilt = doble pasada

    def aplicar(self, sig: np.ndarray, sr: int) -> np.ndarray:
        if self._sos is None or self._sr != sr:
            self.preparar(sr)
        return sosfiltfilt(self._sos, sig).astype(np.float32)

    @property
    def orden(self):
        return self.ORDEN if self._sos is not None else None


# ═══════════════════════════════════════════════════════════════
# Alineación temporal GCC-PHAT
# ═══════════════════════════════════════════════════════════════

class AlineadorGCCPHAT:
    """
    Calcula el delay de una señal respecto a una referencia mediante
    GCC-PHAT (cross-correlación con blanqueo de fase en Fourier).
    """

    def __init__(self, max_delay_seg: float = 0.05):
        self.max_delay_seg = max_delay_seg

    def delay_muestras(self, sig: np.ndarray, ref: np.ndarray, sr: int) -> int:
        """
        Delay de `sig` respecto a `ref` en muestras.
        Positivo → sig llega después de ref.
        """
        n     = len(sig) + len(ref) - 1
        n_fft = int(2 ** np.ceil(np.log2(n)))

        A   = np.fft.rfft(sig, n=n_fft)
        R   = np.fft.rfft(ref, n=n_fft)
        X   = A * np.conj(R)
        den = np.abs(X)
        den[den < 1e-10] = 1e-10
        X  /= den

        cc      = np.fft.irfft(X, n=n_fft)
        max_lag = int(self.max_delay_seg * sr)

        pos_val = cc[:max_lag + 1]
        neg_val = cc[n_fft - max_lag:]

        pi = int(np.argmax(pos_val))
        ni = int(np.argmax(neg_val))

        if pos_val[pi] >= neg_val[ni]:
            return pi
        else:
            return -(max_lag - ni)

    @staticmethod
    def alinear(sig: np.ndarray, delay: int, largo: int) -> np.ndarray:
        """Desplaza sig por -delay muestras y recorta/rellena a `largo`."""
        if delay > 0:
            out = sig[delay:]
        elif delay < 0:
            out = np.pad(sig, (-delay, 0))
        else:
            out = sig.copy()

        if len(out) >= largo:
            return out[:largo]
        return np.pad(out, (0, largo - len(out)))


# ═══════════════════════════════════════════════════════════════
# Detección de onset y offset
# ═══════════════════════════════════════════════════════════════

class DetectorOnsetOffset:
    """
    Detecta onset y offset en una señal de referencia usando
    umbral adaptivo: piso_de_ruido + margen_dB.

    El piso de ruido se estima como la mediana del RMS de frames
    en los primeros `ruido_seg` segundos.
    """

    def __init__(
        self,
        frame_ms: float = 20.0,
        ruido_seg: float = 3.0,
        margen_db: float = 12.0,
        rollon_ms: float = 500.0,
        rolloff_ms: float = 500.0,
    ):
        self.frame_ms   = frame_ms
        self.ruido_seg  = ruido_seg
        self.margen_db  = margen_db
        self.rollon_ms  = rollon_ms
        self.rolloff_ms = rolloff_ms

    def detectar(self, ref: np.ndarray, sr: int) -> tuple[int, int, float, float]:
        """
        Detecta onset y offset sobre la señal de referencia.

        Returns
        -------
        start : int
            Índice de inicio (onset - rollon).
        stop : int
            Índice de fin (offset + rolloff).
        piso_db : float
        umbral_db : float
        """
        frame_n    = max(1, int(sr * self.frame_ms / 1000))
        n_frames   = len(ref) // frame_n

        niveles = np.array([
            self._rms_db(ref[i * frame_n:(i + 1) * frame_n])
            for i in range(n_frames)
        ])

        frames_ruido = min(int(self.ruido_seg * sr / frame_n), n_frames)
        piso_db      = float(np.median(niveles[:frames_ruido]))
        umbral_db    = piso_db + self.margen_db

        sobre = np.where(niveles > umbral_db)[0]
        if len(sobre) == 0:
            onset_frame  = 0
            offset_frame = n_frames - 1
        else:
            onset_frame  = int(sobre[0])
            offset_frame = int(sobre[-1])

        rollon_n  = int(sr * self.rollon_ms  / 1000)
        rolloff_n = int(sr * self.rolloff_ms / 1000)

        start = max(0, onset_frame  * frame_n - rollon_n)
        stop  = min(len(ref), (offset_frame + 1) * frame_n + rolloff_n)

        return start, stop, piso_db, umbral_db

    @staticmethod
    def _rms_db(frame: np.ndarray) -> float:
        rms = np.sqrt(np.mean(frame ** 2))
        return float(20 * np.log10(rms + 1e-10))
