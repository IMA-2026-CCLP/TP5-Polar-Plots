"""ui/audio_play.py — reproducción de una toma (un micrófono / azimut / elevación) desde memoria."""
import os
import tempfile
import numpy as np
import soundfile as sf
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

_player = None      # se mantiene vivo mientras suena
_last_file = None   # WAV de la reproducción anterior (se borra al empezar la siguiente)


def play_signal(x: np.ndarray, sr: int) -> str:
    """Escribe la señal como WAV temporal (normalizada) y la reproduce. Devuelve la ruta del archivo.
    Cada reproducción usa un archivo nuevo: en Windows no se puede sobrescribir uno que está abierto."""
    global _last_file
    x = np.asarray(x, dtype=np.float32).ravel()
    peak = float(np.max(np.abs(x))) or 1.0
    x = 0.9 * x / peak
    fd, path = tempfile.mkstemp(prefix="polar_toma_", suffix=".wav")
    os.close(fd)
    sf.write(path, x, int(sr), subtype="PCM_16")
    pl = player()
    pl.stop()
    pl.setSource(QUrl.fromLocalFile(path))
    pl.play()
    if _last_file and _last_file != path:
        try:
            os.remove(_last_file)
        except OSError:
            pass   # si sigue en uso, queda en la carpeta temporal
    _last_file = path
    return path


def stop() -> None:
    """Detiene la reproducción en curso (si hay)."""
    if _player is not None:
        _player.stop()


def player() -> QMediaPlayer:
    """Reproductor compartido (para la barra de reproducción del diálogo)."""
    global _player
    if _player is None:
        _player = QMediaPlayer()
        _player.setAudioOutput(QAudioOutput())
    return _player
