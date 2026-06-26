"""
ui/html_ribbon.py — HtmlRibbon: reemplazo visual de RibbonBar.

Renderiza shell.html (tab bar + ribbon) en un QWebEngineView.
Expone exactamente la misma API pública que RibbonBar para que
main_window.py sólo necesite cambiar la importación y la construcción.
"""
import json
import os

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel

from ui.bridge import Bridge

_SHELL_PATH = os.path.join(os.path.dirname(__file__), 'shell.html')
_TAB_H    = 50
_RIBBON_H = 112


# ── Proxies de compatibilidad (imitan QWidget.setEnabled / .text / .currentText) ──

class _BtnProxy:
    """Sustituye QPushButton para btn_to_spl y btn_save_mask."""
    def __init__(self, ribbon: 'HtmlRibbon', el_id: str):
        self._r  = ribbon
        self._id = el_id
    def setEnabled(self, enabled: bool):
        self._r._bridge.enableBtn.emit(self._id, enabled)


class _BicoProxy:
    """Sustituye QToolButton para botones tipo ícono deshabilitables."""
    def __init__(self, ribbon: 'HtmlRibbon', el_id: str):
        self._r  = ribbon
        self._id = el_id
    def setEnabled(self, enabled: bool):
        self._r._js(
            f"setBicoEnabled('{self._id}', {'true' if enabled else 'false'})"
        )


class _ValueProxy:
    """Sustituye QLineEdit.text() / QComboBox.currentText() leyendo el state."""
    def __init__(self, state: dict, key: str, default=''):
        self._state   = state
        self._key     = key
        self._default = default
    def text(self):
        return str(self._state.get(self._key, self._default))
    def currentText(self):
        return self.text()


# ── HtmlRibbon ────────────────────────────────────────────────────────────────

class HtmlRibbon(QWidget):
    """
    Drop-in replacement for RibbonBar.
    Usa QWebEngineView + Bridge (QWebChannel) en lugar de widgets Qt.
    La API pública (señales + métodos) es idéntica a RibbonBar.
    """

    # ── Señales idénticas a RibbonBar ─────────────────────────────────────
    tab_changed       = pyqtSignal(int)
    sig_theme_toggled = pyqtSignal()

    sig_load_audio      = pyqtSignal()
    sig_save_tensor     = pyqtSignal()
    sig_load_tensor     = pyqtSignal()
    sig_load_polar_npz  = pyqtSignal()
    sig_save_polar_npz  = pyqtSignal()

    sig_apply_hpf        = pyqtSignal(float)
    sig_align_takes      = pyqtSignal(float, float, object, float)
    sig_align_preview    = pyqtSignal(float, float, object)
    sig_align_ref        = pyqtSignal(object)
    sig_open_calibracion = pyqtSignal()
    sig_to_spl           = pyqtSignal()
    sig_plot_params      = pyqtSignal(object, object, bool, bool, object, float)

    sig_detect_notes     = pyqtSignal(float, float, float, float, object)
    sig_edit_scale       = pyqtSignal()
    sig_preset_changed   = pyqtSignal(str)
    sig_save_mask        = pyqtSignal()
    sig_load_mask        = pyqtSignal()

    sig_compute_dir         = pyqtSignal(str, float, float, int, int)
    sig_save_dir_npz        = pyqtSignal()
    sig_dir_display_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_TAB_H + 1 + _RIBBON_H)

        # Bridge + WebChannel
        self._bridge  = Bridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject('bridge', self._bridge)

        # WebView
        self._view = QWebEngineView()
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._view.page().setWebChannel(self._channel)
        self._view.setUrl(QUrl.fromLocalFile(_SHELL_PATH))
        self._view.loadFinished.connect(self._on_loaded)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._view)

        # Atributos proxy — compatibilidad con accesos directos de main_window
        self.btn_to_spl    = _BtnProxy(self, 'btn-to-spl')
        self.btn_save_mask = _BicoProxy(self, 'bico-save-mask')
        self.combo_bands   = _ValueProxy(self._bridge.state, 'bands',  '1/3')
        self.le_ref_az     = _ValueProxy(self._bridge.state, 'ref_az', '0')
        self.le_ref_th     = _ValueProxy(self._bridge.state, 'ref_th', '0')

        self._wire()

    # ── Conexiones bridge → señales ───────────────────────────────────────
    def _wire(self):
        b = self._bridge
        b.sig_tab_changed.connect(self.tab_changed)
        b.sig_load_audio.connect(self.sig_load_audio)
        b.sig_save_tensor.connect(self.sig_save_tensor)
        b.sig_load_tensor.connect(self.sig_load_tensor)
        b.sig_load_polar_npz.connect(self.sig_load_polar_npz)
        b.sig_save_polar_npz.connect(self.sig_save_polar_npz)
        b.sig_apply_hpf.connect(self.sig_apply_hpf)
        b.sig_align_takes.connect(self.sig_align_takes)
        b.sig_align_preview.connect(self.sig_align_preview)
        b.sig_align_ref.connect(self.sig_align_ref)
        b.sig_open_calibracion.connect(self.sig_open_calibracion)
        b.sig_to_spl.connect(self.sig_to_spl)
        b.sig_plot_params.connect(self.sig_plot_params)
        b.sig_detect_notes.connect(self.sig_detect_notes)
        b.sig_edit_scale.connect(self.sig_edit_scale)
        b.sig_preset_changed.connect(self.sig_preset_changed)
        b.sig_save_mask.connect(self.sig_save_mask)
        b.sig_load_mask.connect(self.sig_load_mask)
        b.sig_compute_dir.connect(self.sig_compute_dir)
        b.sig_save_dir_npz.connect(self.sig_save_dir_npz)
        b.sig_dir_display_changed.connect(self.sig_dir_display_changed)
        b.sig_theme_toggled.connect(self.sig_theme_toggled)

    def _on_loaded(self, ok):
        if not ok:
            return
        from ui.tab_notas import SCALE_PRESETS
        self._bridge.presetsLoaded.emit(json.dumps(list(SCALE_PRESETS.keys())))

    def _js(self, code: str):
        self._view.page().runJavaScript(code)

    # ── API pública idéntica a RibbonBar ──────────────────────────────────

    def _switch_tab(self, idx: int):
        """Cambia el tab visualmente (HTML) y emite tab_changed para el stack."""
        self._js(f"_curTab=-1;switchTab({idx})")
        self._bridge.state['tab'] = idx

    def _update_theme_icon(self, palette: dict):
        """RibbonBar actualiza el ícono; aquí notificamos al HTML."""
        self._bridge.themeChanged.emit(palette['name'])

    def set_ma_loaded(self, ma):
        thetas = list(ma.thetas)
        angles = list(ma.angles)
        self._bridge.maLoaded.emit(json.dumps({
            'thetas': thetas,
            'angles': angles,
            'is_spl': bool(getattr(ma, '_is_spl', False)),
        }))
        # Chip de estado
        n_az = len(angles)
        n_th = len(thetas)
        sr   = getattr(ma, 'sr', 0) // 1000
        spl  = ' · SPL ✓' if getattr(ma, '_is_spl', False) else ''
        self._bridge.statusUpdated.emit(f"{n_az} × {n_th} · {sr} kHz{spl}", True)

    def set_notes_loaded(self, notes: list):
        self._bridge.notesLoaded.emit(json.dumps(notes))

    def set_dir_computed(self, thetas):
        self._bridge.dirComputed.emit(json.dumps([float(t) for t in thetas]))

    def set_dir_status(self, text: str):
        self._bridge.dirStatusChanged.emit(text)

    def get_dir_display_params(self) -> dict:
        s = self._bridge.state
        return dict(
            hz_min      = float(s.get('hz_min', 315.0)),
            hz_max      = float(s.get('hz_max', 10000.0)),
            colorscale  = str(s.get('colorscale', 'Plasma')),
            el_index    = s.get('el_idx'),
            symmetry    = str(s.get('symmetry', 'none')),
            nota        = str(s.get('nota', 'Todo el audio')),
            spec_data   = int(s.get('spec_data', 0)),
            spec_global = bool(s.get('spec_global', True)),
            view_checks = {
                '3d':      bool(s.get('view_3d',      True)),
                'sphere':  bool(s.get('view_sphere',  True)),
                'polar2d': bool(s.get('view_polar2d', True)),
                'spectrum':bool(s.get('view_spectrum', True)),
            },
        )
