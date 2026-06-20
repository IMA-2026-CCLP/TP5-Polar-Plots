"""
ui/styles.py — QSS dark theme
"""
import os as _os

_CHK_ICON_PATH = (
    _os.path.join(_os.path.dirname(__file__), 'icons', 'check.svg')
    .replace('\\', '/')
)

# ── Paleta de referencia (mismos valores en ribbon.py) ────────────────────────
#  Fondo base     #13151f
#  Fondo panel    #1d2035
#  Fondo dark     #0f1119
#  Texto primario #dde3f4
#  Texto secundario #9aa6cc  (≥ 6:1 sobre fondos oscuros)
#  Texto muted    #6b7898   (≥ 4.5:1 sobre fondos oscuros)
#  Acento         #6070d0
# ─────────────────────────────────────────────────────────────────────────────

QSS = """
QWidget {
    background-color: #13151f;
    color: #dde3f4;
    font-family: "Inter", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 10pt;
}

QMainWindow {
    background-color: #0f1119;
}

/* ══════ PANELES ══════ */
#sidebar {
    background-color: #0f1119;
    border-right: 1px solid #252840;
}

#panel_header {
    background: #1d2035;
    border-bottom: 1px solid #252840;
    padding: 10px 16px;
    font-size: 11pt;
    font-weight: 600;
    color: #edf0fa;
    border-radius: 8px 8px 0 0;
}

QGroupBox {
    background: transparent;
    border: 1px solid #252840;
    border-radius: 8px;
    margin-top: 22px;
    padding: 12px 8px 8px;
    font-size: 10pt;
    font-weight: 600;
    color: #9aa6cc;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 1px;
    padding: 0 6px;
    background: transparent;
    color: #9aa6cc;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-size: 9pt;
}

/* ══════ BOTONES ══════ */
QPushButton {
    background: #252840;
    color: #dde3f4;
    border: 1px solid #353a58;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 10pt;
}
QPushButton:hover {
    background: #2e3455;
    border-color: #5060a8;
    color: #edf0fa;
}
QPushButton:pressed {
    background: #1e2240;
}
QPushButton:disabled {
    background: #1d2035;
    color: #505878;
    border-color: #252840;
}

QPushButton#btn_primary {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #5d70cc, stop:1 #4858b8);
    color: #ffffff;
    border: none;
    font-weight: 600;
    font-size: 10.5pt;
    padding: 9px 20px;
    border-radius: 9px;
}
QPushButton#btn_primary:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #6d80dc, stop:1 #5868c8);
}
QPushButton#btn_primary:disabled {
    background: #252840;
    color: #505878;
}

QPushButton#btn_danger {
    background: #3d1f2a;
    color: #f87171;
    border: 1px solid #5a2a38;
    border-radius: 8px;
    padding: 6px 14px;
}
QPushButton#btn_danger:hover {
    background: #4d2535;
    border-color: #f87171;
}

QPushButton#btn_icon {
    background: transparent;
    border: none;
    padding: 4px 8px;
    border-radius: 6px;
    color: #9aa6cc;
}
QPushButton#btn_icon:hover {
    background: #252840;
    color: #dde3f4;
}

/* ══════ INPUTS ══════ */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0f1119;
    border: 1px solid #2e3248;
    border-radius: 7px;
    padding: 6px 10px;
    color: #dde3f4;
    selection-background-color: #4858b8;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #6070d0;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #505878;
    background: #141620;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background: #1d2035;
    border: 1px solid #252840;
    selection-background-color: #252840;
    border-radius: 6px;
    color: #dde3f4;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #252840;
    border: none;
    border-radius: 3px;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #2e3455;
}

/* ══════ PROGRESS BAR ══════ */
QProgressBar {
    background: #0f1119;
    border: 1px solid #252840;
    border-radius: 6px;
    height: 10px;
    text-align: center;
    color: #9aa6cc;
    font-size: 8pt;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #4858b8, stop:1 #6070d0);
    border-radius: 5px;
}

/* ══════ SCROLL ══════ */
QScrollBar:vertical {
    background: #0f1119;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #252840;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #353a58; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #0f1119;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #252840;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #353a58; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ══════ TEXT EDIT (LOG) ══════ */
QTextEdit {
    background: #0c0e16;
    border: 1px solid #252840;
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "Fira Mono", "Courier New", monospace;
    font-size: 9pt;
    color: #9aa6cc;
    selection-background-color: #252840;
}

/* ══════ LISTA / TABLA ══════ */
QListWidget, QTreeWidget, QTableWidget {
    background: #0f1119;
    border: 1px solid #252840;
    border-radius: 8px;
    alternate-background-color: #13151f;
    gridline-color: #252840;
}
QListWidget::item, QTableWidget::item {
    padding: 4px 8px;
    border-radius: 4px;
}
QListWidget::item:hover, QTableWidget::item:hover {
    background: #1d2035;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background: #252840;
    color: #edf0fa;
}
QHeaderView::section {
    background: #1d2035;
    border: none;
    border-right: 1px solid #252840;
    border-bottom: 1px solid #252840;
    padding: 6px 10px;
    color: #9aa6cc;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 0.05em;
}

/* ══════ ETIQUETAS ══════ */
QLabel {
    background: transparent;
}
QLabel#label_title {
    font-size: 15pt;
    font-weight: 700;
    color: #edf0fa;
    letter-spacing: -0.02em;
}
QLabel#label_subtitle {
    font-size: 9.5pt;
    color: #7a86a8;
}
QLabel#label_hint {
    font-size: 10pt;
    color: #8a96be;
}
QLabel#label_badge {
    background: #252840;
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 8.5pt;
    color: #9aa6cc;
}
QLabel#label_ok {
    color: #4fd87a;
    font-weight: 600;
}
QLabel#label_warn {
    color: #ffa94d;
    font-weight: 600;
}
QLabel#label_error {
    color: #f87171;
    font-weight: 600;
}

/* ══════ SEPARADORES ══════ */
QFrame[frameShape="4"] {
    background: #252840;
    border: none;
    max-height: 1px;
}
QFrame[frameShape="5"] {
    background: #252840;
    border: none;
    max-width: 1px;
}

/* ══════ TOOLTIP ══════ */
QToolTip {
    background: #1d2035;
    color: #dde3f4;
    border: 1px solid #353a58;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 9.5pt;
}

/* ══════ TAB ══════ */
QTabWidget::pane {
    border: 1px solid #252840;
    border-radius: 0 8px 8px 8px;
    background: #13151f;
}
QTabBar::tab {
    background: #0f1119;
    border: 1px solid #252840;
    border-bottom: none;
    padding: 8px 22px;
    border-radius: 7px 7px 0 0;
    color: #9aa6cc;
    font-size: 10pt;
}
QTabBar::tab:selected {
    background: #13151f;
    color: #dde3f4;
    border-bottom: 2px solid #6070d0;
}
QTabBar::tab:hover {
    color: #dde3f4;
    background: #1d2035;
}

/* ══════ SLIDER ══════ */
QSlider::groove:horizontal {
    height: 4px;
    background: #252840;
    border-radius: 2px;
    margin: 2px 0;
}
QSlider::handle:horizontal {
    background: #6070d0;
    border: 2px solid #8090e0;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: #8090e0;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #4858b8, stop:1 #6070d0);
    border-radius: 2px;
}

/* ══════ RADIO / CHECKBOX ══════ */
QRadioButton, QCheckBox {
    color: #dde3f4;
    spacing: 8px;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #353a58;
    border-radius: 4px;
    background: #0f1119;
}
QRadioButton::indicator { border-radius: 8px; }
QRadioButton::indicator:checked {
    background: #6070d0;
    border-color: #8090e0;
}
QCheckBox::indicator:checked {
    background: #6070d0;
    border-color: #8090e0;
}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {
    border-color: #6070d0;
}

/* Checkmark image — added via Python string concatenation at module level */

/* ══════ SPLITTER ══════ */
QSplitter::handle {
    background: #252840;
}
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical   { height: 2px; }

/* ══════ DOCK ══════ */
QDockWidget {
    color: #dde3f4;
    font-size: 9.5pt;
}
QDockWidget::title {
    background: #1d2035;
    padding: 4px 8px;
    border-bottom: 1px solid #252840;
}
"""

QSS += f'QCheckBox::indicator:checked {{ image: url("{_CHK_ICON_PATH}"); }}'
