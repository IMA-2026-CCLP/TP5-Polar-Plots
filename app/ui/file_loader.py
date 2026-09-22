"""
ui/file_loader.py — Carga y guardado de audios/sesiones (menú Archivo).

Ya no es una pestaña: MainWindow lo dispara desde el menú Archivo. Los patrones
de nombre de archivo se editan en un diálogo modal y se recuerdan en QSettings;
"Cargar audio" pide sólo la carpeta y procesa de inmediato.
"""
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)
from PyQt6.QtCore import QObject, pyqtSignal

from core.worker import Worker

_DEF_ARRAY = "mic_{MIC}_ang_forte_{H}.wav"
_DEF_REF   = "mic_ref_ang_forte_{H}.wav"


class _PatternsDialog(QDialog):
    def __init__(self, array_pattern: str, ref_pattern: str, parent=None, accept_text: str = "Aceptar"):
        super().__init__(parent)
        self.setWindowTitle("Patrones de nombres de archivo")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        hint = QLabel(
            "<b>{MIC}</b> = elevación (o número) del micrófono &nbsp;·&nbsp; <b>{H}</b> = azimut de la toma.<br>"
            "Sirve para cualquier medición: sólo hay que escribir el patrón con esos dos marcadores."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        self.edit_array = QLineEdit(array_pattern)
        self.edit_ref   = QLineEdit(ref_pattern)
        self.edit_ref.setPlaceholderText("vacío = sin micrófono de referencia")
        form.addRow("Array:", self.edit_array)
        form.addRow("Referencia (opcional):", self.edit_ref)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(accept_text)
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class FileLoader(QObject):
    """ma_ready(MicArray) al terminar una carga; log(str) para el dock de log."""
    ma_ready = pyqtSignal(object)
    log      = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._worker: Worker | None = None
        self._ma = None

    # ── Patrones ──────────────────────────────────────────────────────────
    def patterns(self) -> tuple[str, str]:
        s = self._settings
        return (str(s.value("array_pattern", _DEF_ARRAY)), str(s.value("ref_pattern", _DEF_REF)))

    def edit_patterns(self, parent=None, title: str | None = None, accept_text: str = "Aceptar") -> bool:
        """Modal de patrones; guarda si se acepta. Devuelve True si se aceptó."""
        dlg = _PatternsDialog(*self.patterns(), parent, accept_text)
        if title:
            dlg.setWindowTitle(title)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        self._settings.setValue("array_pattern", dlg.edit_array.text().strip() or _DEF_ARRAY)
        self._settings.setValue("ref_pattern", dlg.edit_ref.text().strip())
        return True

    # ── Carga ─────────────────────────────────────────────────────────────
    def load_audio(self, parent=None):
        """Primero confirma los patrones de nombres de archivo (modal) y recién después pide la carpeta."""
        if not self.edit_patterns(parent, "Cargar audio — patrones de nombres de archivo", "Cargar"):
            return
        path = QFileDialog.getExistingDirectory(
            parent, "Carpeta con los audios de la medición", str(self._settings.value("last_audio_dir", "")))
        if not path:
            return
        self._settings.setValue("last_audio_dir", path)
        arr, ref = self.patterns()

        def _run():
            from mic_array.patron import MicArray
            return MicArray.from_audio(path, arr, ref or None)

        self._start(_run, f"[Carga] Audios de {path}", "Cargando audios…")

    def _start(self, fn, msg: str, label: str):
        if self._worker and self._worker.isRunning():
            return
        self.log.emit(msg + " …")
        self._worker = Worker(fn)
        self._worker.label = label
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self.set_ma)
        self._worker.error.connect(lambda m: self.log.emit(f"[ERROR]\n{m}"))
        self._worker.start()

    def set_ma(self, ma):
        self._ma = ma
        self.log.emit(f"[Carga] Tensor listo — {ma.tensor.shape}")
        self.ma_ready.emit(ma)

