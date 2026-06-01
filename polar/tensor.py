# -*- coding: utf-8 -*-
"""
polar/tensor.py

Función para armar el tensor de mediciones a partir de un directorio
con la siguiente estructura:

    ruta_audio/
        mic_ref/
            mic_ref_ang_forte_0.wav
            mic_ref_ang_forte_10.wav
            ...
        mic_1/
            mic_1_ang_forte_0.wav
            ...
        mic_19/
            ...

El tensor resultante tiene forma:  (azimuth x mics x samples)

    tensor[i_azimuth, i_mic, sample]

    i_azimuth : índice del ángulo de la mesa     (ej: 0°, 10°, ..., 180°)
    i_mic     : índice del micrófono             (índice 0 = mic_ref, luego mic_1 ... mic_19)
    sample    : señal de audio, con zero-padding al final si es necesario

Uso desde un notebook:
    from polar.tensor import armar_tensor
    tensor, sr, angulos, mics = armar_tensor("data/audio/array/forte")

    # mics = ['ref', 1, 2, ..., 19]
    # tensor[0, 0, :]  → mic_ref, ángulo 0°
    # tensor[0, 1, :]  → mic_1,   ángulo 0°
"""

import re
import numpy as np
import soundfile as sf
from pathlib import Path


def tensor(ruta_audio):
    """
    Lee todos los WAVs dentro de `ruta_audio` y arma un tensor 3D.

    Parámetros
    ----------
    ruta_audio : str o Path
        Directorio raíz con subcarpetas por micrófono.
        Ej: "data/audio/array/forte"

    Retorna
    -------
    tensor  : np.ndarray  shape (n_azimuth, n_mics, n_samples), dtype float32
    sr      : int         sample rate (Hz)
    angulos : list[int]   ángulos encontrados, ordenados       [0, 10, ..., 180]
    mics    : list        mics en orden: ['ref', 1, 2, ..., 19]
    """

    ruta_audio = Path(ruta_audio)

    if not ruta_audio.exists():
        raise FileNotFoundError(f"No se encontró el directorio: {ruta_audio}")

    # ------------------------------------------------------------------
    # PASO 1: descubrir qué mics y ángulos hay en el directorio
    # ------------------------------------------------------------------
    patron_carpeta_num = re.compile(r"^mic_(\d+)$")           # mic_1 ... mic_19
    patron_carpeta_ref = re.compile(r"^mic_ref$", re.IGNORECASE)  # mic_ref
    patron_archivo     = re.compile(r"_ang_\w+_(\d+)\.wav$", re.IGNORECASE)

    mics_numericos  = set()
    tiene_ref       = False
    angulos_encontrados = set()
    sr = None

    for carpeta in ruta_audio.iterdir():
        if not carpeta.is_dir():
            continue

        # ¿Es mic_ref?
        if patron_carpeta_ref.match(carpeta.name):
            tiene_ref = True
            _actualizar_angulos_y_sr(carpeta, patron_archivo, angulos_encontrados)
            if sr is None:
                sr = _leer_sr(carpeta)
            continue

        # ¿Es mic_N?
        m = patron_carpeta_num.match(carpeta.name)
        if not m:
            continue  # carpeta desconocida, la ignoramos

        mics_numericos.add(int(m.group(1)))
        _actualizar_angulos_y_sr(carpeta, patron_archivo, angulos_encontrados)
        if sr is None:
            sr = _leer_sr(carpeta)

    if not angulos_encontrados:
        raise ValueError(
            f"No se encontraron audios válidos en: {ruta_audio}\n"
            "Verificá que las subcarpetas se llamen mic_ref o mic_N y los archivos "
            "tengan el formato mic_X_ang_DINAMICA_ANGULO.wav"
        )

    angulos = sorted(angulos_encontrados)

    # mic_ref va primero, luego los numéricos ordenados
    mics_num_sorted = sorted(mics_numericos)
    mics = (['ref'] if tiene_ref else []) + mics_num_sorted

    print(f"  Mics encontrados    : {mics}")
    print(f"  Ángulos encontrados : {angulos}")
    print(f"  Sample rate         : {sr} Hz")

    # ------------------------------------------------------------------
    # PASO 2: calcular el largo máximo escaneando TODOS los archivos
    # ------------------------------------------------------------------
    largo_max = 0

    for mic in mics:
        for angulo in angulos:
            archivo = _buscar_archivo(ruta_audio, mic, angulo)
            if archivo is None:
                continue
            signal, _ = sf.read(archivo)
            if len(signal) > largo_max:
                largo_max = len(signal)

    print(f"  Largo máximo        : {largo_max} samples  ({largo_max / sr:.2f} s)")

    # ------------------------------------------------------------------
    # PASO 3: armar el tensor inicializado en cero
    # ------------------------------------------------------------------
    tensor = np.zeros((len(angulos), len(mics), largo_max), dtype=np.float32)

    print(f"\n  Armando tensor {tensor.shape} ...")

    for i_az, angulo in enumerate(angulos):
        for i_mic, mic in enumerate(mics):
            archivo = _buscar_archivo(ruta_audio, mic, angulo)

            if archivo is None:
                print(f"    [SKIP] mic_{mic}  ang_{angulo}° → no encontrado")
                continue

            signal, _ = sf.read(archivo)

            # Insertamos la señal; el resto del slice ya es cero (zero-padding)
            tensor[i_az, i_mic, :len(signal)] = signal

        print(f"    Ángulo {angulo:>4}° → OK")

    print(f"\n  Tensor listo.")
    print(f"  Shape    : {tensor.shape}  (azimuth x mics x samples)")
    print(f"  Tamaño   : {tensor.nbytes / 1024 / 1024:.1f} MB")
    print(f"  mics[0]  = mic_ref  |  mics[1] = mic_1  |  mics[-1] = mic_{mics[-1]}")

    return tensor, sr, angulos, mics


# ----------------------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------------------

def _actualizar_angulos_y_sr(carpeta, patron_archivo, angulos_set):
    """Escanea una carpeta y agrega los ángulos encontrados al set."""
    for archivo in carpeta.glob("*.wav"):
        m = patron_archivo.search(archivo.name)
        if m:
            angulos_set.add(int(m.group(1)))


def _leer_sr(carpeta):
    """Lee el sample rate del primer WAV que encuentre en la carpeta."""
    for archivo in carpeta.glob("*.wav"):
        _, sr = sf.read(archivo)
        return sr
    return None


def _buscar_archivo(ruta_audio, mic, angulo):
    """
    Busca el WAV de un mic y ángulo dentro de ruta_audio/mic_X/.
    mic puede ser un int (mic numérico) o el string 'ref'.
    No asume la dinámica en el nombre del archivo.
    Retorna el Path si lo encuentra, None si no.
    """
    carpeta = ruta_audio / f"mic_{mic}"
    if not carpeta.exists():
        return None

    # Patrón: mic_X_ang_CUALQUIERCOSA_ANGULO.wav
    patron = re.compile(
        rf"mic_{mic}_ang_\w+_{angulo}\.wav$", re.IGNORECASE
    )

    for archivo in carpeta.glob("*.wav"):
        if patron.search(archivo.name):
            return archivo

    return None