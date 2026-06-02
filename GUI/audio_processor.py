"""
Procesamiento de audio con filtros de tercio de octava.

Retorna niveles por banda keyed por frecuencia de banda ISO normalizada.
Los filtros se crean una única vez en el primer audio (lazy initialization)
basándose en el sampling frequency real del archivo.
"""
from typing import Optional, List, Dict
import numpy as np
import funciones as fn
import soundfile as sf

# ─── Constantes ──────────────────────────────────────────────────────────────
G = 10**(3/10)     # Cociente de octava base 10 (norma IEC 61260)
f_r = 1000         # Hz, frecuencia de referencia
N = 10             # Orden de los filtros

# Bandas ISO 1/3 de octava para normalización/display
ISO_BANDS = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
]

# Bandas ISO por octava para normalización/display
ISO_BANDS_OCTAVA = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


# ─── Cache para filters (lazy initialization) ─────────────────────────────────
_filter_state = {
    'fs': None,
    'sos_filters': {}, # Key: Frecuencia ISO (float) -> Value: Matriz SOS
    'real_centers': {} # Opcional: Guardado para debugging
}

def get_real_center_freq(iso_freq: float) -> float:
    """
    Calcula la frecuencia central exacta (f_m) según la norma IEC 61260.
    """
    # 10 * log10(f / f_r) nos da el índice relativo exacto en tercios de octava
    x = round(10 * np.log10(iso_freq / f_r))
    return f_r * (10 ** (x / 10.0))

def process_audio(
    filepath: str,
    band_width: int,
    selected_bands: Optional[List[float]] = None,
) -> Dict[float, float]:
    """
    Procesa un archivo de audio y devuelve niveles por banda.
    Inicializa los filtros SOS al procesar el primer archivo o cuando 
    se solicitan nuevas bandas, y valida que el fs se mantenga constante.
    """
    # 1. Leer audio (dtype=float32 para menor overhead de memoria)
    wav, fs_wav = sf.read(filepath, dtype=np.float32)
    
    # 2. Definir qué bandas procesar
    bands_to_process = selected_bands if selected_bands is not None else ISO_BANDS

    # 3. Validación de Sampling Frequency (Fs)
    if _filter_state['fs'] is None:
        # Primer audio procesado: registramos el fs
        _filter_state['fs'] = fs_wav
    elif _filter_state['fs'] != fs_wav:
        # Audios subsiguientes: abortar si el fs cambia, porque rompería el DSP
        raise ValueError(
            f"Inconsistencia de Sampling Rate: el banco de filtros fue "
            f"inicializado con fs={_filter_state['fs']} Hz, pero "
            f"'{filepath}' tiene fs={fs_wav} Hz."
        )

    # Identificar qué bandas faltan crear en el caché
    # print(f'[AudioProcessor] Procesando con ancho de octava: {band_width}')
    if band_width == 1:
        missing_iso_bands = [b for b in bands_to_process if b in ISO_BANDS_OCTAVA and b not in _filter_state['sos_filters']]
    else:
        missing_iso_bands = [b for b in bands_to_process if b in ISO_BANDS and b not in _filter_state['sos_filters']]
    # print(f'[AudioProcessor] Missing_bands: {missing_iso_bands}')
    
    if missing_iso_bands:
        # Armar array de frecuencias matemáticas reales
        f_reals = np.array([get_real_center_freq(b) for b in missing_iso_bands])
        
        # Generar el banco de filtros de una sola vez
        sos_bank = fn.sos_filter_bank(band_width, f_reals, N, fs_wav, G)
        
        # Guardar en el caché emparejando la key ISO con su filtro correspondiente
        for iso_f, f_real, sos in zip(missing_iso_bands, f_reals, sos_bank):
            _filter_state['sos_filters'][iso_f] = sos
            _filter_state['real_centers'][iso_f] = f_real

    #  Armar el array/lista de filtros en el orden exacto de las bandas solicitadas
    filtros_tercio = [_filter_state['sos_filters'][b] for b in bands_to_process]
    
    #  Procesar el audio (asumiendo que fn.process_audio retorna niveles db en el mismo orden)
    niveles_db = fn.process_audio(wav, filtros_tercio)
    
    #  Empaquetar el resultado en un diccionario relacionando la key ISO con el nivel DB
    result = {iso_f: float(db) for iso_f, db in zip(bands_to_process, niveles_db)}
    return result