# -*- coding: utf-8 -*-
"""
ReproductorAudio: reproduce el audio de referencia sincronizado con el slider.
Usa sounddevice para control preciso del tiempo de reproducción.
"""

from __future__ import annotations
import threading
import numpy as np

try:
    import sounddevice as sd
    _SD_DISPONIBLE = True
except ImportError:
    _SD_DISPONIBLE = False

from PyQt6.QtCore import QObject, pyqtSignal


class ReproductorAudio(QObject):
    """
    Reproduce un array de audio (float32) sincronizado con la posición del slider.

    Signals
    -------
    posicion_s(float)  : posición actual de reproducción en segundos
    """

    posicion_s = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio:   np.ndarray | None = None
        self._sr:      int               = 48000
        self._pos:     int               = 0       # muestra actual
        self._stream:  "sd.OutputStream | None" = None
        self._lock     = threading.Lock()
        self._activo   = False

    # ── API pública ─────────────────────────────────────────────────────────

    def cargar(self, audio: np.ndarray, sr: int):
        """Carga el audio de referencia."""
        self.detener()
        self._audio = audio.astype(np.float32)
        self._sr    = sr
        self._pos   = 0

    def seek(self, tiempo_s: float):
        """Mueve la posición de reproducción a `tiempo_s` segundos."""
        if self._audio is None:
            return
        with self._lock:
            self._pos = int(np.clip(tiempo_s * self._sr, 0, len(self._audio) - 1))

    def reproducir(self, desde_s: float | None = None):
        """Inicia la reproducción. Si `desde_s` se da, hace seek primero."""
        if not _SD_DISPONIBLE or self._audio is None:
            return
        if desde_s is not None:
            self.seek(desde_s)
        if self._activo:
            return
        self._activo = True
        self._stream = sd.OutputStream(
            samplerate=self._sr,
            channels=1,
            dtype="float32",
            blocksize=1024,
            callback=self._callback,
            finished_callback=self._on_fin,
        )
        self._stream.start()

    def detener(self):
        """Detiene la reproducción."""
        self._activo = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    @property
    def posicion_actual_s(self) -> float:
        return self._pos / max(self._sr, 1)

    @property
    def duracion_s(self) -> float:
        if self._audio is None:
            return 0.0
        return len(self._audio) / self._sr

    @property
    def disponible(self) -> bool:
        return _SD_DISPONIBLE

    # ── Internos ─────────────────────────────────────────────────────────────

    def _callback(self, outdata, frames, time, status):
        with self._lock:
            if not self._activo or self._audio is None:
                outdata[:] = 0
                raise sd.CallbackStop()

            inicio = self._pos
            fin    = inicio + frames
            chunk  = self._audio[inicio:fin]

            if len(chunk) < frames:
                outdata[:len(chunk), 0] = chunk
                outdata[len(chunk):, 0] = 0
                self._pos   = len(self._audio)
                self._activo = False
                raise sd.CallbackStop()

            outdata[:, 0] = chunk
            self._pos    = fin

        self.posicion_s.emit(self._pos / self._sr)

    def _on_fin(self):
        self._activo = False
        self._stream = None
