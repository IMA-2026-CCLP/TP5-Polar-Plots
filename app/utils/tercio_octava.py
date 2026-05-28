# -*- coding: utf-8 -*-
"""
Bandas de 1/3 de octava según IEC 61260.
Cálculo de SPL por banda a partir de la STFT.
"""

import numpy as np


# ═══════════════════════════════════════════════════════════════
# Bandas IEC 61260
# ═══════════════════════════════════════════════════════════════

# Cociente de octava base-10 (IEC 61260 §1.4)
_G = 10 ** (3 / 10)

# Frecuencias centrales de referencia (Hz), serie exacta IEC 61260
_FRECS_CENTRALES_REF = [
    100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
    1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000,
]


def bandas_tercio_octava(f_min: float = 100.0, f_max: float = 10000.0):
    """
    Devuelve (f_centro, f_inf, f_sup) para cada banda de 1/3 oct
    entre f_min y f_max Hz (serie exacta IEC 61260).

    Returns
    -------
    f_centro : np.ndarray  shape (n_bandas,)
    f_inf    : np.ndarray  shape (n_bandas,)
    f_sup    : np.ndarray  shape (n_bandas,)
    """
    frecs = [f for f in _FRECS_CENTRALES_REF if f_min <= f <= f_max]
    f_centro = np.array(frecs, dtype=float)
    f_inf    = f_centro / _G ** (1 / 6)
    f_sup    = f_centro * _G ** (1 / 6)
    return f_centro, f_inf, f_sup


# ═══════════════════════════════════════════════════════════════
# Calculador de SPL por banda a partir de STFT
# ═══════════════════════════════════════════════════════════════

class CalculadorSPL:
    """
    Convierte la magnitud de la STFT a SPL por bandas de 1/3 oct.

    Parámetros
    ----------
    sr         : int    — sample rate
    n_fft      : int    — número de puntos de la FFT (= frame_size)
    f_min / f_max : float — rango de bandas a calcular
    """

    def __init__(self, sr: int, n_fft: int,
                 f_min: float = 100.0, f_max: float = 10000.0):
        self.sr    = sr
        self.n_fft = n_fft
        self.f_centro, self.f_inf, self.f_sup = bandas_tercio_octava(f_min, f_max)
        self.n_bandas = len(self.f_centro)

        # Frecuencias de los bins de la STFT (solo lado positivo)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

        # Máscaras booleanas: (n_bandas, n_bins)
        self._mascaras = np.array([
            (freqs >= fi) & (freqs < fs)
            for fi, fs in zip(self.f_inf, self.f_sup)
        ])  # shape (n_bandas, n_bins)

    def calcular_tensor(self, stft_mag: np.ndarray) -> np.ndarray:
        """
        Convierte la magnitud de la STFT a SPL por bandas de 1/3 oct.

        Parámetros
        ----------
        stft_mag : np.ndarray  shape (..., n_bins, n_frames)
            Magnitud de la STFT (salida de np.abs(np.stft(...))).

        Returns
        -------
        spl : np.ndarray  shape (..., n_bandas, n_frames)  float32
            SPL en dB para cada banda y frame.
        """
        # (..., n_bins, n_frames) → iterar sobre bandas
        spl_list = []
        for mascara in self._mascaras:
            # Sumar energía (magnitud²) en los bins de la banda
            energia = np.sum(
                stft_mag[..., mascara, :] ** 2,
                axis=-2
            )  # shape (..., n_frames)
            spl_list.append(10 * np.log10(energia + 1e-10))

        # stack → (..., n_bandas, n_frames)
        return np.stack(spl_list, axis=-2).astype(np.float32)
