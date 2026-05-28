# -*- coding: utf-8 -*-
"""Lectura de archivos WAV y descubrimiento de archivos por plantilla."""

import re
from math import gcd
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def resamplear(sig: np.ndarray, sr_orig: int, sr_dest: int) -> np.ndarray:
    """Resamples `sig` de sr_orig a sr_dest usando filtro polifásico."""
    if sr_orig == sr_dest:
        return sig
    g    = gcd(sr_orig, sr_dest)
    up   = sr_dest // g
    down = sr_orig // g
    return resample_poly(sig, up, down).astype(np.float32)


class LectorWAV:
    """
    Carga archivos WAV como arrays mono float32.

    Si se especifica `sr_objetivo`, resamplea automáticamente cualquier
    archivo cuyo SR difiera. Esto permite mezclar grabaciones a 44.1 kHz
    y 48 kHz en el mismo proyecto.
    """

    def __init__(self, sr_objetivo: Optional[int] = None):
        self._sr_objetivo = sr_objetivo

    def cargar(self, path) -> tuple:
        """
        Carga un WAV, lo convierte a mono float32 y resamplea si es necesario.

        Returns
        -------
        sig : np.ndarray   señal mono float32 al sr_objetivo (o al sr nativo)
        sr  : int          sr_objetivo si se fijó, o sr nativo del archivo
        """
        sig, sr_nativo = sf.read(str(path), dtype="float32")
        if sig.ndim > 1:
            sig = sig[:, 0]

        if self._sr_objetivo is not None and sr_nativo != self._sr_objetivo:
            sig = resamplear(sig, sr_nativo, self._sr_objetivo)
            return sig, self._sr_objetivo

        return sig, sr_nativo

    def cargar_detectar_sr(self, path) -> tuple:
        """Igual a cargar() pero además devuelve el sr_nativo del archivo."""
        sig, sr_nativo = sf.read(str(path), dtype="float32")
        if sig.ndim > 1:
            sig = sig[:, 0]

        sr_salida = sr_nativo
        if self._sr_objetivo is not None and sr_nativo != self._sr_objetivo:
            sig       = resamplear(sig, sr_nativo, self._sr_objetivo)
            sr_salida = self._sr_objetivo

        return sig, sr_salida, sr_nativo

    @property
    def sr_objetivo(self) -> Optional[int]:
        return self._sr_objetivo


class Descubridor:
    """
    Descubre y clasifica archivos WAV en una carpeta plana usando
    plantillas de nombre configurables.

    Plantilla de ejemplo:
        mics → "mic_{MIC}_ang_{DIN}_{ANG}.wav"
        refs → "mic_ref_ang_{DIN}_{ANG}.wav"

    Marcadores disponibles: {MIC}, {DIN}, {ANG}
    """

    _MARCADORES = {
        "{MIC}": r"(?P<mic>\d+)",
        "{DIN}": r"(?P<din>[^_]+)",   # todo lo que no sea _ (más robusto que \w+)
        "{ANG}": r"(?P<ang>\d+)",
    }

    def __init__(self, template_mics: str, template_refs: str):
        self._template_mics = template_mics
        self._template_refs = template_refs
        self._re_mics = self._compilar(template_mics)
        self._re_refs = self._compilar(template_refs)

    # ── API pública ─────────────────────────────────────────────────────────

    def patron_mics(self) -> str:
        return self._re_mics.pattern

    def patron_refs(self) -> str:
        return self._re_refs.pattern

    def descubrir(self, carpeta, dinamica: str):
        """
        Recorre carpeta (plana) y clasifica cada WAV.

        Returns
        -------
        mics      : dict[(mic_idx, ang_mesa)] → Path
        refs      : dict[ang_mesa] → Path
        ignorados : list[str]
        """
        carpeta = Path(carpeta)
        mics     = {}
        refs     = {}
        ignorados = []

        for wav in sorted(carpeta.glob("*.wav")):
            nombre = wav.name

            m = self._re_mics.match(nombre)
            if m and m.group("din").lower() == dinamica.lower():
                mic = int(m.group("mic"))
                ang = int(m.group("ang"))
                mics[(mic, ang)] = wav
                continue

            m = self._re_refs.match(nombre)
            if m and m.group("din").lower() == dinamica.lower():
                ang = int(m.group("ang"))
                refs[ang] = wav
                continue

            ignorados.append(nombre)

        return mics, refs, ignorados

    # ── Internos ─────────────────────────────────────────────────────────────

    @classmethod
    def _compilar(cls, template: str) -> re.Pattern:
        """
        Convierte la plantilla en un patrón regex.

        Divide la plantilla en los marcadores conocidos, escapa las partes
        literales y reconstruye el patrón completo.
        """
        # Ordenar marcadores de mayor a menor longitud para evitar
        # solapamientos parciales en el split
        marcadores = sorted(cls._MARCADORES.keys(), key=len, reverse=True)

        # Construir patrón parte por parte
        partes = []
        resto  = template
        while resto:
            encontrado = False
            for marcador in marcadores:
                if resto.startswith(marcador):
                    partes.append(cls._MARCADORES[marcador])
                    resto = resto[len(marcador):]
                    encontrado = True
                    break
            if not encontrado:
                # Escapar el carácter literal actual
                partes.append(re.escape(resto[0]))
                resto = resto[1:]

        return re.compile("".join(partes) + "$", re.IGNORECASE)
