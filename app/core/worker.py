"""
core/worker.py — Worker genérico QThread con captura de stdout.

Uso:
    def mi_funcion(arg1, arg2):
        print("procesando...")
        return resultado

    w = Worker(mi_funcion, arg1, arg2)
    w.log.connect(mi_log_widget.append)
    w.finished.connect(lambda result: ...)
    w.error.connect(lambda msg: ...)
    w.start()
"""
import sys
import io
import threading
import traceback

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class _StreamCapture(io.TextIOBase):
    """Redirige sys.stdout a una señal Qt."""

    def __init__(self, signal):
        super().__init__()
        self._signal = signal

    def write(self, text: str) -> int:
        if text.strip():
            self._signal.emit(text.rstrip())
        return len(text)

    def flush(self):
        pass


class _Activity(QObject):
    """Cuántas tareas de fondo hay en curso y cómo se llama la última (para el indicador de la barra de estado)."""
    changed  = pyqtSignal(int, str)
    progress = pyqtSignal(int, int)      # hecho, total (lo informan las funciones de mic_array)


activity = _Activity()
_running: list = []
_lock = threading.Lock()


def _mark(label: str, start: bool):
    with _lock:
        if start:
            _running.append(label)
        else:
            _running.remove(label)
        n, last = len(_running), (_running[-1] if _running else "")
    activity.changed.emit(n, last)


def report(done: int, total: int):
    """Progreso de la tarea en curso; se llama desde el hilo del Worker."""
    activity.progress.emit(int(done), int(total))


class Worker(QThread):
    """
    Ejecuta cualquier callable en un hilo separado.
    Captura todo lo que se imprima con print() y lo emite por log.
    """
    log      = pyqtSignal(str)    # línea de texto capturada de stdout
    finished = pyqtSignal(object) # resultado del callable (puede ser None)
    error    = pyqtSignal(str)    # traceback completo si hay excepción
    label    = ""                # texto del indicador de progreso (asignarlo antes de start())

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        label = self.label or "Procesando…"
        try:
            import mic_array.patron as _patron
            _patron.progress_callback = report
        except ImportError:
            pass
        _mark(label, True)
        capture = _StreamCapture(self.log)
        old_stdout = sys.stdout
        sys.stdout = capture
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            sys.stdout = old_stdout
            _mark(label, False)
