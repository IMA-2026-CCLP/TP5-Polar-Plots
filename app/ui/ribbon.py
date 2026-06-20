"""
ui/ribbon.py — Ribbon global estilo Word con qtawesome.
"""
import os as _os
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
    QToolButton, QPushButton, QFrame, QComboBox, QLineEdit,
    QCheckBox, QStackedWidget, QButtonGroup, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon

from ui import theme as _theme

# ── Constantes de layout (no dependen del tema) ───────────────────────────────
_ICON_SZ   = QSize(26, 26)
_BTN_W     = 62
_BTN_H     = 68
_RIBBON_H  = 100
_TAB_H     = 30
_FONT_SMALL = "font-size: 9pt; font-family: 'Segoe UI', Inter, sans-serif;"
_FONT_GROUP = "font-size: 8pt;"

_CHK_ICON_PATH = (
    _os.path.join(_os.path.dirname(__file__), 'icons', 'check.svg')
    .replace('\\', '/')
)
_HPF_ICON_PATH = (
    _os.path.join(_os.path.dirname(__file__), 'icons', 'hpf.svg')
    .replace('\\', '/')
)

TAB_LABELS = ["Archivo", "Procesamiento", "Notas", "Directividad"]
TAB_IDX    = {name: i for i, name in enumerate(TAB_LABELS)}


# ── Helpers (sin setStyleSheet — estilos vienen del QSS global) ───────────────

def _icon(name: str, color: str = "#9aa6cc"):
    return qta.icon(name, color=color)


def _tool_btn(icon_name: str, label: str, w: int = _BTN_W) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(_icon(icon_name))
    btn.setIconSize(_ICON_SZ)
    btn.setText(label)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setFixedSize(w, _BTN_H)
    return btn


def _vsep() -> QWidget:
    sep = QWidget()
    sep.setObjectName("ribbon_vsep")
    sep.setFixedSize(1, 60)
    return sep


def _le(default: str = "", width: int = 60, placeholder: str = "") -> QLineEdit:
    w = QLineEdit(str(default))
    w.setPlaceholderText(placeholder)
    w.setFixedWidth(width)
    w.wheelEvent = lambda e: e.ignore()
    return w


def _combo(width: int = 100) -> QComboBox:
    w = QComboBox()
    w.setFixedWidth(width)
    w.wheelEvent = lambda e: e.ignore()
    return w


def _lbl(text: str, _color: str = "") -> QLabel:
    """Crea un QLabel; el color viene del QSS global (ignoramos _color)."""
    return QLabel(text)


def _chk(text: str) -> QCheckBox:
    return QCheckBox(text)


def _svg_tool_btn(svg_path: str, label: str, w: int = _BTN_W) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(QIcon(svg_path))
    btn.setIconSize(_ICON_SZ)
    btn.setText(label)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setFixedSize(w, _BTN_H)
    return btn


def _accent_btn(label: str) -> QPushButton:
    btn = QPushButton(label)
    btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #5d70cc, stop:1 #4858b8);
            color: #ffffff; border: none; font-weight: 600;
            font-size: 9pt; padding: 5px 10px; border-radius: 6px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #6d80dc, stop:1 #5868c8);
        }
        QPushButton:disabled { background: #1e2238; color: #404868; }
    """)
    return btn


def _group(title: str) -> tuple[QWidget, QVBoxLayout]:
    outer = QWidget()
    outer.setStyleSheet("background: transparent;")
    v = QVBoxLayout(outer)
    v.setContentsMargins(6, 3, 6, 0)
    v.setSpacing(2)
    body = QVBoxLayout()
    body.setSpacing(2)
    v.addLayout(body, 1)
    lbl = QLabel(title)
    lbl.setObjectName("ribbon_group_lbl")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return outer, body


# ── Ribbon principal ──────────────────────────────────────────────────────────

class RibbonBar(QWidget):
    """
    Ribbon global estilo Word.

    Señales emitidas (conectar en MainWindow):
      tab_changed(int)
      sig_theme_toggled()
      # Archivo
      sig_load_audio, sig_save_tensor, sig_load_tensor
      sig_load_polar_npz, sig_save_polar_npz
      # Procesamiento
      sig_apply_hpf(float)
      sig_align_takes(float, float, object)
      sig_align_ref()
      sig_open_calibracion()
      sig_plot_params(object, object, bool, bool, object)
      # Notas
      sig_detect_notes(float, float, float, object)
      # Directividad
      sig_compute_dir(str, float, float, int, int)
      sig_save_dir_npz()
      sig_dir_display_changed()
    """

    tab_changed      = pyqtSignal(int)
    sig_theme_toggled = pyqtSignal()

    sig_load_audio      = pyqtSignal()
    sig_save_tensor     = pyqtSignal()
    sig_load_tensor     = pyqtSignal()
    sig_load_polar_npz  = pyqtSignal()
    sig_save_polar_npz  = pyqtSignal()

    sig_apply_hpf       = pyqtSignal(float)
    sig_align_takes     = pyqtSignal(float, float, object)
    sig_align_ref       = pyqtSignal()
    sig_open_calibracion= pyqtSignal()
    sig_plot_params     = pyqtSignal(object, object, bool, bool, object)

    sig_detect_notes    = pyqtSignal(float, float, float, object)

    sig_compute_dir     = pyqtSignal(str, float, float, int, int)
    sig_save_dir_npz    = pyqtSignal()
    sig_dir_display_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_TAB_H + 1 + _RIBBON_H)
        self._build_ui()

    # ── Construcción ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_tab_bar())

        sep = QFrame()
        sep.setObjectName("ribbon_sep")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        self._stack = QStackedWidget()
        self._stack.setObjectName("ribbon_stack")
        self._stack.setFixedHeight(_RIBBON_H)
        self._stack.addWidget(self._panel_archivo())
        self._stack.addWidget(self._panel_procesamiento())
        self._stack.addWidget(self._panel_notas())
        self._stack.addWidget(self._panel_directividad())
        root.addWidget(self._stack)

    def _make_tab_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("ribbon_tab_bar")
        bar.setFixedHeight(_TAB_H)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(0)

        logo = QLabel("⬡")
        logo.setObjectName("ribbon_logo")
        lay.addWidget(logo)

        self._tab_grp = QButtonGroup(bar)
        self._tab_grp.setExclusive(True)
        for i, name in enumerate(TAB_LABELS):
            btn = QToolButton()
            btn.setText(name)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setObjectName("ribbon_tab")
            btn.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            self._tab_grp.addButton(btn, i)
            lay.addWidget(btn)

        lay.addStretch()

        self._btn_theme = QToolButton()
        self._btn_theme.setObjectName("ribbon_theme_toggle")
        self._btn_theme.setFixedHeight(_TAB_H)
        self._btn_theme.setToolTip("Cambiar tema claro/oscuro")
        self._update_theme_icon(_theme.current())
        self._btn_theme.clicked.connect(self.sig_theme_toggled)
        lay.addWidget(self._btn_theme)

        return bar

    def _switch_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self.tab_changed.emit(idx)

    # ── Panel Archivo ─────────────────────────────────────────────────────────

    def _panel_archivo(self) -> QWidget:
        w, lay = _panel_base()

        grp, body = _group("AUDIO")
        row = QHBoxLayout(); row.setSpacing(2)
        self.btn_load_audio = _tool_btn('fa5s.folder-open', 'Cargar\naudio')
        self.btn_load_audio.clicked.connect(self.sig_load_audio)
        row.addWidget(self.btn_load_audio)
        self.btn_load_tensor = _tool_btn('fa5s.file-import', 'Cargar\ntensor')
        self.btn_load_tensor.clicked.connect(self.sig_load_tensor)
        row.addWidget(self.btn_load_tensor)
        self.btn_save_tensor = _tool_btn('fa5s.save', 'Guardar\ntensor')
        self.btn_save_tensor.setEnabled(False)
        self.btn_save_tensor.clicked.connect(self.sig_save_tensor)
        row.addWidget(self.btn_save_tensor)
        body.addLayout(row)
        lay.addWidget(grp)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp2, body2 = _group("PATRÓN POLAR")
        row2 = QHBoxLayout(); row2.setSpacing(2)
        self.btn_load_polar = _tool_btn('fa5s.chart-bar', 'Cargar\nNPZ polar')
        self.btn_load_polar.clicked.connect(self.sig_load_polar_npz)
        row2.addWidget(self.btn_load_polar)
        self.btn_save_polar = _tool_btn('fa5s.file-export', 'Guardar\nNPZ polar')
        self.btn_save_polar.setEnabled(False)
        self.btn_save_polar.clicked.connect(self.sig_save_polar_npz)
        row2.addWidget(self.btn_save_polar)
        body2.addLayout(row2)
        lay.addWidget(grp2)

        lay.addStretch()
        return w

    # ── Panel Procesamiento ───────────────────────────────────────────────────

    def _panel_procesamiento(self) -> QWidget:
        w, lay = _panel_base()

        grp, body = _group("VISTA")
        grp.setMaximumWidth(330)

        cols = QHBoxLayout(); cols.setSpacing(10)

        c1 = QVBoxLayout(); c1.setSpacing(4)
        th_row = QHBoxLayout(); th_row.setSpacing(4)
        th_row.addWidget(_lbl("θ")); self.combo_theta = _combo(90); th_row.addWidget(self.combo_theta); th_row.addStretch()
        az_row = QHBoxLayout(); az_row.setSpacing(4)
        az_row.addWidget(_lbl("Az")); self.combo_az = _combo(90); az_row.addWidget(self.combo_az); az_row.addStretch()
        c1.addLayout(th_row); c1.addLayout(az_row)
        cols.addLayout(c1)

        c2 = QVBoxLayout(); c2.setSpacing(4)
        self.chk_envelope = _chk("Envolvente"); self.chk_envelope.setChecked(True)
        self.chk_db = _chk("dB"); self.chk_db.toggled.connect(self._on_db_toggled)
        c2.addWidget(self.chk_envelope); c2.addWidget(self.chk_db)
        cols.addLayout(c2)

        c3 = QVBoxLayout(); c3.setSpacing(4)
        mn_row = QHBoxLayout(); mn_row.setSpacing(4)
        mn_row.addWidget(_lbl("Min"))
        self.le_ymin = _le("", 54, "-60"); mn_row.addWidget(self.le_ymin); mn_row.addStretch()
        mx_row = QHBoxLayout(); mx_row.setSpacing(4)
        mx_row.addWidget(_lbl("Max"))
        self.le_ymax = _le("", 54, "0"); mx_row.addWidget(self.le_ymax); mx_row.addStretch()
        c3.addLayout(mn_row); c3.addLayout(mx_row)
        cols.addLayout(c3)

        body.addLayout(cols)

        for sig in (self.combo_theta.currentIndexChanged, self.combo_az.currentIndexChanged):
            sig.connect(lambda _: self._emit_plot_params())
        for chk in (self.chk_envelope, self.chk_db):
            chk.toggled.connect(lambda _: self._emit_plot_params())
        for le in (self.le_ymin, self.le_ymax):
            le.editingFinished.connect(self._emit_plot_params)

        lay.addWidget(grp)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp2, body2 = _group("HPF")
        grp2.setMaximumWidth(150)

        fq_row = QHBoxLayout(); fq_row.setSpacing(4)
        fq_row.addWidget(_lbl("Frec:"))
        self.le_hpf = _le("200", 68, "Hz")
        fq_row.addWidget(self.le_hpf)
        fq_row.addStretch()
        body2.addLayout(fq_row)
        body2.addStretch()

        self.btn_hpf = _svg_tool_btn(_HPF_ICON_PATH, 'Aplicar', 66)
        self.btn_hpf.setEnabled(False)
        self.btn_hpf.clicked.connect(self._emit_hpf)
        body2.addWidget(self.btn_hpf, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(grp2)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp3, body3 = _group("ALINEACIÓN")

        al_row = QHBoxLayout(); al_row.setSpacing(6)
        al_row.addWidget(_lbl("Onset:"))
        self.le_onset = _le("1.0", 50)
        al_row.addWidget(self.le_onset)
        al_row.addWidget(_lbl("s"))
        al_row.addSpacing(6)
        al_row.addWidget(_lbl("Umbral:"))
        self.le_thresh = _le("-40", 50)
        al_row.addWidget(self.le_thresh)
        al_row.addWidget(_lbl("dBFS"))
        al_row.addSpacing(6)
        al_row.addWidget(_lbl("Mic Ref:"))
        self.combo_align_theta = _combo(80)
        al_row.addWidget(self.combo_align_theta)
        body3.addLayout(al_row)

        body3.addStretch()

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.btn_align_takes = _accent_btn("Alinear tomas")
        self.btn_align_takes.setEnabled(False)
        self.btn_align_takes.clicked.connect(self._emit_align_takes)
        btn_row.addWidget(self.btn_align_takes)
        self.btn_align_ref = _accent_btn("Alinear Mics")
        self.btn_align_ref.setEnabled(False)
        self.btn_align_ref.clicked.connect(self.sig_align_ref)
        btn_row.addWidget(self.btn_align_ref)
        body3.addLayout(btn_row)

        lay.addWidget(grp3)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp4, body4 = _group("CALIBRAR")
        body4.addStretch()
        self.btn_calibrar = _tool_btn('fa5s.sliders-h', 'Calibrar', 78)
        self.btn_calibrar.setEnabled(False)
        self.btn_calibrar.clicked.connect(self.sig_open_calibracion)
        body4.addWidget(self.btn_calibrar, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(grp4)

        lay.addStretch()
        return w

    # ── Panel Notas ───────────────────────────────────────────────────────────

    def _panel_notas(self) -> QWidget:
        w, lay = _panel_base()

        grp, body = _group("DETECCIÓN")
        r1 = QHBoxLayout(); r1.setSpacing(4)
        r1.addWidget(_lbl("Min dur (s):"))
        self.le_note_dur = _le("0.3", 48)
        r1.addWidget(self.le_note_dur)
        r1.addWidget(_lbl("Margen (s):"))
        self.le_note_margin = _le("0.05", 48)
        r1.addWidget(self.le_note_margin)
        body.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(4)
        r2.addWidget(_lbl("Umbral (dBFS):"))
        self.le_note_thresh = _le("-40", 48)
        r2.addWidget(self.le_note_thresh)
        r2.addWidget(_lbl("Ref θ:"))
        self.combo_note_theta = _combo(72)
        r2.addWidget(self.combo_note_theta)
        body.addLayout(r2)

        body.addStretch()

        self.btn_detect = _tool_btn('fa5s.music', 'Detectar\nnotas', 80)
        self.btn_detect.setEnabled(False)
        self.btn_detect.clicked.connect(self._emit_detect_notes)
        body.addWidget(self.btn_detect, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(grp)

        lay.addStretch()
        return w

    # ── Panel Directividad ────────────────────────────────────────────────────

    def _panel_directividad(self) -> QWidget:
        from plot.balloon import COLORSCALES
        w, lay = _panel_base()

        grp, body = _group("CÁLCULO DIRECTIVIDAD")
        grp.setMaximumWidth(285)
        body.setSpacing(5)
        body.addStretch(1)

        g = QGridLayout()
        g.setHorizontalSpacing(5)
        g.setVerticalSpacing(5)
        g.setColumnStretch(7, 1)

        g.addWidget(_lbl("Bandas:"), 0, 0)
        self.combo_bands = _combo(52)
        self.combo_bands.addItems(["1/3", "octave"])
        g.addWidget(self.combo_bands, 0, 1)
        g.addWidget(_lbl("Hz:"), 0, 2)
        self.le_hz_min = _le("200", 44, "mín")
        self.le_hz_min.editingFinished.connect(self.sig_dir_display_changed)
        g.addWidget(self.le_hz_min, 0, 3)
        g.addWidget(_lbl("–"), 0, 4, alignment=Qt.AlignmentFlag.AlignCenter)
        self.le_hz_max = _le("8000", 48, "máx")
        self.le_hz_max.editingFinished.connect(self.sig_dir_display_changed)
        g.addWidget(self.le_hz_max, 0, 5)

        g.addWidget(_lbl("Ref Az:"), 1, 0)
        self.le_ref_az = _le("0", 36)
        g.addWidget(self.le_ref_az, 1, 1)
        g.addWidget(_lbl("θ:"), 1, 2)
        self.le_ref_th = _le("0", 36)
        g.addWidget(self.le_ref_th, 1, 3)

        body.addLayout(g)
        body.addSpacing(4)
        self.btn_compute = _accent_btn("Calcular")
        self.btn_compute.setEnabled(False)
        self.btn_compute.clicked.connect(self._emit_compute_dir)
        body.addWidget(self.btn_compute)
        body.addStretch(1)

        lay.addWidget(grp)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp2, body2 = _group("NOTA")
        grp2.setMaximumWidth(155)
        body2.addStretch(1)
        self.combo_nota = _combo(135)
        self.combo_nota.addItem("Todo el audio")
        self.combo_nota.currentTextChanged.connect(self.sig_dir_display_changed)
        body2.addWidget(self.combo_nota, alignment=Qt.AlignmentFlag.AlignHCenter)
        body2.addStretch(1)
        lay.addWidget(grp2)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp3, body3 = _group("VISUALIZACIÓN")
        grp3.setMaximumWidth(390)
        body3.setSpacing(5)
        body3.addStretch(1)

        gv = QGridLayout()
        gv.setHorizontalSpacing(5)
        gv.setVerticalSpacing(5)
        gv.setColumnStretch(6, 1)

        gv.addWidget(_lbl("Color:"), 0, 0)
        self.combo_cs = _combo(88)
        self.combo_cs.addItems(list(COLORSCALES.keys()))
        self.combo_cs.setCurrentText("Plasma")
        self.combo_cs.currentTextChanged.connect(self.sig_dir_display_changed)
        gv.addWidget(self.combo_cs, 0, 1)

        gv.addWidget(_lbl("Elev:"), 0, 2)
        self.combo_el = _combo(78)
        self.combo_el.addItem("Auto (0°)")
        self.combo_el.currentIndexChanged.connect(self.sig_dir_display_changed)
        gv.addWidget(self.combo_el, 0, 3)

        gv.addWidget(_lbl("Sim:"), 0, 4)
        self.combo_sym = _combo(108)
        self.combo_sym.addItems(["Sin simetría", "XZ (izq↔der)", "XY (sup↔inf)", "XZ + XY"])
        self.combo_sym.currentIndexChanged.connect(self.sig_dir_display_changed)
        gv.addWidget(self.combo_sym, 0, 5)

        body3.addLayout(gv)

        r3b = QHBoxLayout(); r3b.setSpacing(12)
        r3b.addStretch()
        self._view_checks: dict[str, QCheckBox] = {}
        for label, mode in [("3D","3d"),("Esfera","sphere"),("Polar 2D","polar2d"),("Espectro","spectrum")]:
            chk = _chk(label); chk.setChecked(True)
            chk.toggled.connect(self.sig_dir_display_changed)
            self._view_checks[mode] = chk
            r3b.addWidget(chk)
        r3b.addStretch()
        body3.addLayout(r3b)
        body3.addStretch(1)

        lay.addWidget(grp3)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp4, body4 = _group("ESPECTRO")
        grp4.setMaximumWidth(195)
        body4.setSpacing(5)
        body4.addStretch(1)

        ge = QGridLayout()
        ge.setHorizontalSpacing(5)
        ge.setVerticalSpacing(5)
        ge.setColumnStretch(2, 1)

        ge.addWidget(_lbl("Audio:"), 0, 0)
        self.combo_spec_data = _combo(138)
        self.combo_spec_data.addItems(["Originales", "Igualados en nivel"])
        self.combo_spec_data.currentIndexChanged.connect(self.sig_dir_display_changed)
        ge.addWidget(self.combo_spec_data, 0, 1)

        ge.addWidget(_lbl("Vista:"), 1, 0)
        self.combo_spec_view = _combo(138)
        self.combo_spec_view.addItems(["Global", "Por toma"])
        self.combo_spec_view.currentIndexChanged.connect(self.sig_dir_display_changed)
        ge.addWidget(self.combo_spec_view, 1, 1)

        body4.addLayout(ge)
        body4.addStretch(1)

        lay.addWidget(grp4)
        lay.addWidget(_vsep(), alignment=Qt.AlignmentFlag.AlignVCenter)

        grp5, body5 = _group("GUARDAR")
        grp5.setMaximumWidth(100)
        body5.addStretch(1)
        self.btn_save_dir = _tool_btn('fa5s.file-export', 'Guardar\nNPZ polar', 84)
        self.btn_save_dir.setEnabled(False)
        self.btn_save_dir.clicked.connect(self.sig_save_dir_npz)
        body5.addWidget(self.btn_save_dir, alignment=Qt.AlignmentFlag.AlignHCenter)
        body5.addStretch(1)
        lay.addWidget(grp5)

        self.lbl_dir_status = _lbl("Sin datos.")
        self.lbl_dir_status.setWordWrap(True)
        self.lbl_dir_status.setMaximumWidth(130)
        self.lbl_dir_status.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.lbl_dir_status, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addStretch()
        return w

    # ── Slots internos ────────────────────────────────────────────────────────

    def _on_db_toggled(self, checked: bool):
        if checked:
            self.chk_envelope.setChecked(True)
            self.chk_envelope.setEnabled(False)
        else:
            self.chk_envelope.setEnabled(True)
        self._emit_plot_params()

    def _emit_plot_params(self):
        theta   = self._parse_theta(self.combo_theta.currentText())
        az_text = self.combo_az.currentText()
        azimuth = None if az_text == "Todos" else _safe_int(az_text.rstrip("°"))
        env     = self.chk_envelope.isChecked()
        db      = self.chk_db.isChecked()
        try:
            mn, mx = self.le_ymin.text().strip(), self.le_ymax.text().strip()
            yrange = [float(mn), float(mx)] if mn and mx else None
        except ValueError:
            yrange = None
        self.sig_plot_params.emit(theta, azimuth, env, db, yrange)

    def _emit_hpf(self):
        try:
            hz = float(self.le_hpf.text())
        except ValueError:
            hz = 200.0
        self.sig_apply_hpf.emit(hz)

    def _emit_align_takes(self):
        try:
            onset  = float(self.le_onset.text())
            thresh = float(self.le_thresh.text())
        except ValueError:
            onset, thresh = 1.0, -40.0
        theta = self._parse_theta(self.combo_align_theta.currentText())
        self.sig_align_takes.emit(onset, thresh, theta)

    def _emit_detect_notes(self):
        try:
            dur    = float(self.le_note_dur.text())
            margin = float(self.le_note_margin.text())
            thresh = float(self.le_note_thresh.text())
        except ValueError:
            dur, margin, thresh = 0.3, 0.05, -40.0
        theta = self._parse_theta(self.combo_note_theta.currentText())
        self.sig_detect_notes.emit(dur, margin, thresh, theta)

    def _emit_compute_dir(self):
        try:
            hz_min = float(self.le_hz_min.text())
            hz_max = float(self.le_hz_max.text())
            ref_az = int(float(self.le_ref_az.text()))
            ref_th = int(float(self.le_ref_th.text()))
        except ValueError:
            hz_min, hz_max, ref_az, ref_th = 200.0, 8000.0, 0, 0
        self.sig_compute_dir.emit(
            self.combo_bands.currentText(), hz_min, hz_max, ref_az, ref_th
        )

    # ── API de tema ───────────────────────────────────────────────────────────

    def _update_theme_icon(self, palette: dict):
        """Actualiza el ícono del botón de toggle según el tema activo."""
        if palette['name'] == 'dark':
            self._btn_theme.setText("☀")
            self._btn_theme.setToolTip("Cambiar a tema claro")
        else:
            self._btn_theme.setText("🌙")
            self._btn_theme.setToolTip("Cambiar a tema oscuro")

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _parse_theta(self, text: str):
        if not text or text == "ref":
            return "ref"
        return _safe_int(text.rstrip("°")) or "ref"

    # ── API pública ───────────────────────────────────────────────────────────

    def sym_type(self) -> str:
        return ("none", "azimuth", "elevation", "both")[self.combo_sym.currentIndex()]

    def set_ma_loaded(self, ma):
        self.combo_theta.blockSignals(True)
        self.combo_az.blockSignals(True)
        self.combo_align_theta.blockSignals(True)
        self.combo_note_theta.blockSignals(True)

        self.combo_theta.clear()
        self.combo_align_theta.clear()
        self.combo_note_theta.clear()
        for th in ma.thetas:
            lbl = "ref" if th == "ref" else f"{th}°"
            self.combo_theta.addItem(lbl)
            self.combo_align_theta.addItem(lbl)
            self.combo_note_theta.addItem(lbl)

        ref_idx = next((i for i, t in enumerate(ma.thetas) if t == "ref"), 0)
        self.combo_theta.setCurrentIndex(ref_idx)
        self.combo_align_theta.setCurrentIndex(ref_idx)
        self.combo_note_theta.setCurrentIndex(ref_idx)

        self.combo_az.clear()
        self.combo_az.addItem("Todos")
        for az in ma.angles:
            self.combo_az.addItem(f"{az}°")

        self.combo_theta.blockSignals(False)
        self.combo_az.blockSignals(False)
        self.combo_align_theta.blockSignals(False)
        self.combo_note_theta.blockSignals(False)

        self.btn_save_tensor.setEnabled(True)
        self.btn_hpf.setEnabled(True)
        self.btn_align_takes.setEnabled(True)
        self.btn_align_ref.setEnabled(True)
        self.btn_calibrar.setEnabled(True)
        self.btn_detect.setEnabled(True)
        self.btn_compute.setEnabled(ma._is_spl)

        self._emit_plot_params()

    def set_notes_loaded(self, notes: list[str]):
        self.combo_nota.blockSignals(True)
        self.combo_nota.clear()
        self.combo_nota.addItem("Todo el audio")
        for n in notes:
            self.combo_nota.addItem(n)
        self.combo_nota.blockSignals(False)

    def set_dir_computed(self, thetas):
        self.combo_el.blockSignals(True)
        self.combo_el.clear()
        self.combo_el.addItem("Auto (0°)")
        for t in thetas:
            self.combo_el.addItem(f"{t:.0f}°")
        self.combo_el.blockSignals(False)
        self.btn_save_dir.setEnabled(True)
        self.btn_save_polar.setEnabled(True)

    def set_dir_status(self, text: str):
        self.lbl_dir_status.setText(text)

    def get_dir_display_params(self) -> dict:
        try:
            hz_min = float(self.le_hz_min.text())
            hz_max = float(self.le_hz_max.text())
        except ValueError:
            hz_min, hz_max = 200.0, 8000.0
        el_idx = None if self.combo_el.currentIndex() == 0 else self.combo_el.currentIndex() - 1
        return dict(
            hz_min       = hz_min,
            hz_max       = hz_max,
            colorscale   = self.combo_cs.currentText(),
            el_index     = el_idx,
            symmetry     = self.sym_type(),
            nota         = self.combo_nota.currentText(),
            spec_data    = self.combo_spec_data.currentIndex(),
            spec_global  = (self.combo_spec_view.currentIndex() == 0),
            view_checks  = {m: c.isChecked() for m, c in self._view_checks.items()},
        )


# ── Helpers de panel ──────────────────────────────────────────────────────────

def _panel_base() -> tuple[QWidget, QHBoxLayout]:
    w = QWidget()
    w.setObjectName("ribbon_panel")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(6, 3, 6, 2)
    lay.setSpacing(0)
    return w, lay


def _safe_int(text) -> int | None:
    try:
        return int(text)
    except (ValueError, TypeError):
        return None
