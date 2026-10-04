"""ui/audio_play.py — reproducción de una toma (un micrófono / azimut / elevación) desde memoria."""
import os
import tempfile
import numpy as np
import soundfile as sf
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

_player = None   # se mantiene vivo mientras suena


def play_signal(x: np.ndarray, sr: int) -> str:
    """Escribe la señal como WAV temporal (normalizada) y la reproduce. Devuelve la ruta del archivo."""
    global _player
    x = np.asarray(x, dtype=np.float32).ravel()
    peak = float(np.max(np.abs(x))) or 1.0
    x = 0.9 * x / peak
    path = os.path.join(tempfile.gettempdir(), "polar_toma.wav")
    sf.write(path, x, int(sr), subtype="PCM_16")
    if _player is None:
        _player = QMediaPlayer()
        _player.setAudioOutput(QAudioOutput())
    _player.setSource(QUrl.fromLocalFile(path))
    _player.play()
    return path
