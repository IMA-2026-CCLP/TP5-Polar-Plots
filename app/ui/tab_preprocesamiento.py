"""
ui/tab_preprocesamiento.py — Vista de señales (sin ribbon propio).
Los controles están en el ribbon global (ui/ribbon.py).
"""
import os
import tempfile

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from core.worker import Worker
from plot.waveform import build_waveform_html, build_rms_html


class TabPreprocesamiento(QWidget):
    ma_updated = pyqtSignal(object)
    log        = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ma           = None
        self._worker: Worker | None = None
        self._plot_workers: list[Worker] = []
        self._plot_tmp: str | None = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._web = QWebEngineView()
        self._web.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        # Fondo oscuro en la página Chromium para evitar el flash blanco
        self._web.page().setBackgroundColor(QColor("#13151f"))
        self._web.setStyleSheet("background:#13151f;")
        # Inicializar Chromium inmediatamente con un placeholder oscuro.
        # Esto evita el flash de GPU al mostrar el widget por primera vez.
        self._web.setHtml(
            '<html><body style="background:#13151f;margin:0;padding:0"></body></html>'
        )
        lay.addWidget(self._web)

    # ── API pública (llamada desde MainWindow / Ribbon) ───────────────────────

    def set_ma(self, ma):
        self._ma = ma

    def refresh_plot(self, theta, azimuth, env: bool, db: bool, yrange):
        if self._ma is None:
            return
        ma = self._ma

        def _build():
            return build_waveform_html(
                ma, theta=theta, azimuth=azimuth,
                envelope=env, dB=db, yrange=yrange,
            )

        self._run_plot_worker(_build)

    def apply_hpf(self, hz: float):
        if self._ma is None or self._busy():
            return
        self.log.emit(f"[Procesamiento] Aplicando HPF {hz:.0f} Hz…")
        self._worker = Worker(lambda: self._run_hpf(hz))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def align_takes(self, onset: float, thresh: float, theta):
        if self._ma is None or self._busy():
            return
        self.log.emit(f"[Procesamiento] Alineando tomas (onset={onset}s, θ={theta})…")
        self._worker = Worker(lambda: self._run_align_takes(onset, thresh, theta))
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def align_ref(self):
        if self._ma is None or self._busy():
            return
        self.log.emit("[Procesamiento] Alineando a referencia (GCC-PHAT)…")
        self._worker = Worker(self._run_align_ref)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_op_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── Operaciones internas ──────────────────────────────────────────────────

    def _run_hpf(self, hz):
        self._ma.hpf(hz)
        return self._ma

    def _run_align_takes(self, onset, thresh, theta):
        self._ma.align_takes(target_onset=onset, theta=theta, threshold_dB=thresh)
        return self._ma

    def _run_align_ref(self):
        self._ma.align_to_ref()
        return self._ma

    def _on_op_done(self, ma):
        self._ma = ma
        self.ma_updated.emit(ma)
        self.log.emit("[Procesamiento] Listo.")

    def _on_error(self, msg: str):
        self.log.emit(f"[ERROR]\n{msg}")

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _run_plot_worker(self, fn):
        w = Worker(fn)
        w.finished.connect(self._set_html)
        w.error.connect(lambda msg: self.log.emit(f"[Plot error] {msg}"))
        self._plot_workers = [x for x in self._plot_workers if x.isRunning()]
        self._plot_workers.append(w)
        w.start()

    def _set_html(self, html: str):
        if self._plot_tmp is None:
            fd, path = tempfile.mkstemp(suffix=".html", prefix="ppanalyzer_")
            os.close(fd)
            self._plot_tmp = path
        with open(self._plot_tmp, "w", encoding="utf-8") as f:
            f.write(html)
        self._web.setUrl(QUrl.fromLocalFile(self._plot_tmp))
