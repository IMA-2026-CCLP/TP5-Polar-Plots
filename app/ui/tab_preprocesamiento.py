"""
ui/tab_preprocesamiento.py — Vista de señales (sin ribbon propio).
Los controles están en el ribbon global (ui/ribbon.py).

Render nativo con pyqtgraph (ui/waveform_editor.py): permite inspeccionar y
corregir la alineación arrastrando el cursor de onset.
"""
import numpy as np

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal

from core.worker import Worker
from ui.waveform_editor import WaveformEditorWidget


class TabPreprocesamiento(QWidget):
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma           = None
        self._worker: Worker | None = None
        self._target_onset = 1.0
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._editor = WaveformEditorWidget()
        self._editor.log.connect(self.log)
        self._editor.onset_dragged.connect(self._on_onset_dragged)
        lay.addWidget(self._editor)

    # ── API pública (llamada desde MainWindow / Ribbon) ───────────────────────

    def set_ma(self, ma):
        self._ma = ma
        self._editor.set_ma(ma)

    def refresh_plot(self, theta, azimuth, env: bool, db: bool, yrange, smoothing: float = 20.0):
        if self._ma is None:
            return
        self._editor.render(theta, azimuth, env, db, yrange, smoothing)

    def set_align_params(self, target_onset: float, threshold_dB: float, theta):
        self._target_onset = float(target_onset)
        self._editor.set_align_params(target_onset, threshold_dB, theta)

    def apply_theme(self, palette: dict):
        self._editor.apply_theme(palette)

    def apply_hpf(self, hz: float):
        if self._ma is None or self._busy():
            return
        self.log.emit(f"[Procesamiento] Aplicando HPF {hz:.0f} Hz…")
        self._worker = Worker(lambda: self._run_hpf(hz))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def align_takes(self, onset: float, thresh: float, theta, window_ms: float = 50.0):
        if self._ma is None or self._busy():
            return
        self.log.emit(f"[Procesamiento] Alineando tomas (onset={onset}s, θ={theta}, ventana={window_ms:.0f}ms)…")
        self._worker = Worker(lambda: self._run_align_takes(onset, thresh, theta, window_ms))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def align_ref(self, gcc_thresh=None):
        if self._ma is None or self._busy():
            return
        thr_str = f"{gcc_thresh} dBFS" if gcc_thresh is not None else "sin umbral"
        self.log.emit(f"[Procesamiento] Alineando a referencia (GCC-PHAT, {thr_str})…")
        self._worker = Worker(lambda: self._run_align_ref(gcc_thresh))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── Alineación manual por toma (cursor arrastrado) ─────────────────────────

    def _on_onset_dragged(self, az_idx: int, onset_s: float):
        """
        El usuario marcó el onset real de una toma arrastrando el cursor.
        Desplaza SOLO esa toma para que ese instante caiga en target_onset,
        igual que align_takes pero para un único azimuth.
        """
        if self._ma is None or self._busy():
            return
        ma = self._ma
        n  = ma.n_samples
        onset  = int(round(onset_s * ma.sr))
        target = int(round(self._target_onset * ma.sr))
        shift  = target - onset
        if shift == 0:
            return

        if not ma.tensor.flags['WRITEABLE']:
            ma.tensor = np.array(ma.tensor, dtype=np.float32)

        tmp = np.zeros((ma.n_thetas, n), dtype=np.float32)
        if shift > 0:
            tmp[:, shift:] = ma.tensor[az_idx, :, :n - shift]
        else:
            tmp[:, :n + shift] = ma.tensor[az_idx, :, -shift:]
        ma.tensor[az_idx] = tmp

        self.log.emit(
            f"[Procesamiento] Toma {ma.angles[az_idx]}° desplazada "
            f"{shift:+d} smp ({shift / ma.sr * 1000:+.0f} ms) — onset manual."
        )
        self.ma_updated.emit(ma)

    # ── Operaciones internas ──────────────────────────────────────────────────

    def _run_hpf(self, hz):
        self._ma.hpf(hz)
        return self._ma

    def _run_align_takes(self, onset, thresh, theta, window_ms):
        self._ma.align_takes(target_onset=onset, theta=theta, threshold_dB=thresh, window_ms=window_ms)
        return self._ma

    def _run_align_ref(self, gcc_thresh):
        self._ma.align_to_ref(energy_threshold_dB=gcc_thresh)
        return self._ma

    def _on_op_done(self, ma):
        self._ma = ma
        self.ma_updated.emit(ma)
        self.log.emit("[Procesamiento] Listo.")

    def _on_error(self, msg: str):
        self.log.emit(f"[ERROR]\n{msg}")

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()
