# -*- coding: utf-8 -*-
"""Constantes y valores por defecto de la aplicación."""

APP_NAME = "Analizador de Directividad Vocal"
APP_VERSION = "1.0"

# Configuración del array por defecto
DEFAULT_N_MICS        = 19
DEFAULT_ANG_INICIO    = 0      # grados
DEFAULT_ANG_FIN       = 180    # grados
DEFAULT_PASO_MESA     = 10     # grados

# Plantillas de nombre por defecto
DEFAULT_TEMPLATE_MICS = "mic_{MIC}_ang_{DIN}_{ANG}.wav"
DEFAULT_TEMPLATE_REFS = "mic_ref_ang_{DIN}_{ANG}.wav"

# Preprocesamiento por defecto
DEFAULT_FC_HZ         = 100    # frecuencia de corte filtro FIR (Hz)
DEFAULT_RIPPLE_DB     = 60     # atenuación filtro Kaiser (dB)
DEFAULT_WIDTH_HZ      = 40     # ancho banda de transición (Hz)
DEFAULT_RUIDO_SEG     = 3.0    # segundos para estimar piso de ruido
DEFAULT_MARGEN_DB     = 12     # margen sobre piso para detección onset (dB)
DEFAULT_ROLLON_MS     = 500    # ms antes del onset a conservar
DEFAULT_ROLLOFF_MS    = 500    # ms después del offset a conservar
DEFAULT_FRAME_MS      = 10     # tamaño de frame STFT en ms

# Referencia de calibración
P_REF = 2e-5   # 20 µPa

# Calibración SPL: 94 dBSPL = −3 dBFS  →  offset = 94 − (−3) = 97 dB
# Medido con pistófono o fuente de referencia sobre el micrófono de referencia.
DEFAULT_CALIBRACION_DB = 97.0   # dBSPL − dBFS

# Ángulo de referencia para el mic de referencia
ANG_REF_AUDIO = 90   # ángulo de la grabación de referencia para reproducir
