"""
ui/bridge.py — QObject expuesto al JS via QWebChannel.

El HTML llama a los slots de este objeto para notificar acciones del usuario.
HtmlRibbon escucha las señales de este objeto y las reenvía a MainWindow.
"""
import json
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class Bridge(QObject):

    # ── Python → JS (JS se subscribe con bridge.<sig>.connect(fn)) ───────────
    statusUpdated    = pyqtSignal(str, bool)   # text, ok
    maLoaded         = pyqtSignal(str)          # JSON: {thetas, angles, is_spl}
    themeChanged     = pyqtSignal(str)          # 'dark' | 'light'
    notesLoaded      = pyqtSignal(str)          # JSON list of note names
    presetsLoaded    = pyqtSignal(str)          # JSON list of preset names
    dirComputed      = pyqtSignal(str)          # JSON list of thetas
    dirStatusChanged = pyqtSignal(str)          # status text
    enableBtn        = pyqtSignal(str, bool)    # html element id, enabled

    # ── JS → Python (HtmlRibbon conecta a estas) ──────────────────────────────
    sig_tab_changed        = pyqtSignal(int)
    sig_load_audio         = pyqtSignal()
    sig_save_tensor        = pyqtSignal()
    sig_load_tensor        = pyqtSignal()
    sig_load_polar_npz     = pyqtSignal()
    sig_save_polar_npz     = pyqtSignal()
    sig_apply_hpf          = pyqtSignal(float)
    sig_align_takes        = pyqtSignal(float, float, object, float)
    sig_align_ref          = pyqtSignal(object)
    sig_align_preview      = pyqtSignal(float, float, object)
    sig_open_calibracion   = pyqtSignal()
    sig_to_spl             = pyqtSignal()
    sig_plot_params        = pyqtSignal(object, object, bool, bool, object, float)
    sig_detect_notes       = pyqtSignal(float, float, float, float, object)
    sig_edit_scale         = pyqtSignal()
    sig_preset_changed     = pyqtSignal(str)
    sig_save_mask          = pyqtSignal()
    sig_load_mask          = pyqtSignal()
    sig_compute_dir        = pyqtSignal(str, float, float, int, int)
    sig_save_dir_npz       = pyqtSignal()
    sig_dir_display_changed = pyqtSignal()
    sig_theme_toggled      = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Estado actual de los controles del ribbon
        self.state = {
            'tab':        3,
            'theta':      'ref',  'az':        'Todos',
            'envelope':   True,   'db':         False,
            'smooth':     20.0,   'ymin':       None,   'ymax': None,
            'hpf_hz':     200.0,
            'onset':      1.0,    'thresh':    -40.0,   'window_ms': 50.0,
            'align_theta':'ref',  'gcc_thresh': None,
            'bands':      '1/3',  'hz_min':    315.0,   'hz_max': 10000.0,
            'ref_az':     0,      'ref_th':     0,
            'colorscale': 'Plasma','el_idx':    None,
            'symmetry':   'none', 'nota':       'Todo el audio',
            'spec_data':  0,      'spec_global': True,
            'view_3d':    True,   'view_sphere': True,
            'view_polar2d': True, 'view_spectrum': True,
            'note_tol':   50.0,   'note_purity': 0.8,
            'note_start': 0.0,    'note_grad':   25.0,
            'note_theta': 'ref',
        }

    # ── Slots llamados desde JS ───────────────────────────────────────────────

    @pyqtSlot(int)
    def tabClicked(self, idx):
        self.state['tab'] = idx
        self.sig_tab_changed.emit(idx)

    @pyqtSlot()
    def loadAudio(self):
        self.sig_load_audio.emit()

    @pyqtSlot()
    def saveTensor(self):
        self.sig_save_tensor.emit()

    @pyqtSlot()
    def loadTensor(self):
        self.sig_load_tensor.emit()

    @pyqtSlot()
    def loadPolarNpz(self):
        self.sig_load_polar_npz.emit()

    @pyqtSlot()
    def savePolarNpz(self):
        self.sig_save_polar_npz.emit()

    @pyqtSlot(str)
    def updateState(self, json_str: str):
        """JS llama esto para sincronizar el estado de un control."""
        try:
            self.state.update(json.loads(json_str))
        except Exception:
            pass

    @pyqtSlot()
    def emitPlotParams(self):
        th_text = self.state.get('theta', 'ref')
        az_text = self.state.get('az', 'Todos')
        theta   = self._parse_theta(str(th_text))
        azimuth = None if az_text == 'Todos' else _safe_int(str(az_text).rstrip('°'))
        env     = bool(self.state.get('envelope', True))
        db      = bool(self.state.get('db', False))
        ymin    = self.state.get('ymin')
        ymax    = self.state.get('ymax')
        yrange  = [float(ymin), float(ymax)] if ymin is not None and ymax is not None else None
        smooth  = float(self.state.get('smooth', 20.0))
        self.sig_plot_params.emit(theta, azimuth, env, db, yrange, smooth)

    @pyqtSlot()
    def applyHpf(self):
        self.sig_apply_hpf.emit(float(self.state.get('hpf_hz', 200.0)))

    @pyqtSlot()
    def alignTakes(self):
        self.sig_align_takes.emit(
            float(self.state.get('onset', 1.0)),
            float(self.state.get('thresh', -40.0)),
            self._parse_theta(str(self.state.get('align_theta', 'ref'))),
            float(self.state.get('window_ms', 50.0)),
        )

    @pyqtSlot()
    def alignRef(self):
        gcc = self.state.get('gcc_thresh')
        self.sig_align_ref.emit(float(gcc) if gcc is not None else None)

    @pyqtSlot()
    def emitAlignPreview(self):
        self.sig_align_preview.emit(
            float(self.state.get('onset', 1.0)),
            float(self.state.get('thresh', -40.0)),
            self._parse_theta(str(self.state.get('align_theta', 'ref'))),
        )

    @pyqtSlot()
    def openCalibracion(self):
        self.sig_open_calibracion.emit()

    @pyqtSlot()
    def toSpl(self):
        self.sig_to_spl.emit()

    @pyqtSlot()
    def detectNotes(self):
        self.sig_detect_notes.emit(
            float(self.state.get('note_tol', 50.0)),
            float(self.state.get('note_purity', 0.8)),
            float(self.state.get('note_start', 0.0)),
            float(self.state.get('note_grad', 25.0)),
            self._parse_theta(str(self.state.get('note_theta', 'ref'))),
        )

    @pyqtSlot()
    def editScale(self):
        self.sig_edit_scale.emit()

    @pyqtSlot(str)
    def presetChanged(self, name: str):
        self.state['note_preset'] = name
        self.sig_preset_changed.emit(name)

    @pyqtSlot()
    def saveMask(self):
        self.sig_save_mask.emit()

    @pyqtSlot()
    def loadMask(self):
        self.sig_load_mask.emit()

    @pyqtSlot()
    def computeDir(self):
        self.sig_compute_dir.emit(
            str(self.state.get('bands', '1/3')),
            float(self.state.get('hz_min', 315.0)),
            float(self.state.get('hz_max', 10000.0)),
            int(self.state.get('ref_az', 0)),
            int(self.state.get('ref_th', 0)),
        )

    @pyqtSlot()
    def saveDirNpz(self):
        self.sig_save_dir_npz.emit()

    @pyqtSlot()
    def dirDisplayChanged(self):
        self.sig_dir_display_changed.emit()

    @pyqtSlot()
    def themeToggled(self):
        self.sig_theme_toggled.emit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_theta(self, text: str):
        if not text or text in ('ref', 'Todos'):
            return 'ref'
        v = _safe_int(text.rstrip('°'))
        return v if v is not None else 'ref'


def _safe_int(text) -> int | None:
    try:
        return int(text)
    except (ValueError, TypeError):
        return None
