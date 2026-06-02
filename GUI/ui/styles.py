"""
ui/styles.py — QSS dark theme
"""

QSS = """
/* ══════════════════════════════
   BASE
══════════════════════════════ */
QWidget {
    background-color: #1a1d27;
    color: #c8ccd8;
    font-family: "Inter", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 10pt;
}

QMainWindow {
    background-color: #12141e;
}

/* ══════════════════════════════
   PANELES
══════════════════════════════ */
#sidebar {
    background-color: #12141e;
    border-right: 1px solid #2a2d3e;
}

#panel_header {
    background: #1f2235;
    border-bottom: 1px solid #2a2d3e;
    padding: 10px 16px;
    font-size: 11pt;
    font-weight: 600;
    color: #e8ecf4;
    border-radius: 8px 8px 0 0;
}

QGroupBox {
    background: #1f2235;
    border: 1px solid #2a2d3e;
    border-radius: 10px;
    margin-top: 24px;
    padding: 10px;
    font-size: 11pt;
    font-weight: 600;
    color: #7c8aaa;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -2px;
    padding: 0 6px;
    background: #1f2235;
    color: #7c8aaa;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-size: 10pt;
}

/* ══════════════════════════════
   BOTONES
══════════════════════════════ */
QPushButton {
    background: #2e3248;
    color: #c8ccd8;
    border: 1px solid #3b3f58;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 10pt;
}
QPushButton:hover {
    background: #363b58;
    border-color: #5865a0;
    color: #e8ecf4;
}
QPushButton:pressed {
    background: #2a2e44;
}
QPushButton:disabled {
    background: #1f2235;
    color: #4a4f68;
    border-color: #2a2d3e;
}

QPushButton#btn_primary {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #5865a0, stop:1 #4253a0);
    color: #ffffff;
    border: none;
    font-weight: 600;
    font-size: 10.5pt;
    padding: 9px 20px;
    border-radius: 9px;
}
QPushButton#btn_primary:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #6878c0, stop:1 #5265b8);
}
QPushButton#btn_primary:disabled {
    background: #2a2d3e;
    color: #4a4f68;
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
    color: #7c8aaa;
}
QPushButton#btn_icon:hover {
    background: #2a2d3e;
    color: #c8ccd8;
}

/* ══════════════════════════════
   INPUTS
══════════════════════════════ */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #12141e;
    border: 1px solid #2a2d3e;
    border-radius: 7px;
    padding: 6px 10px;
    color: #c8ccd8;
    selection-background-color: #4253a0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #5865a0;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #4a4f68;
    background: #181a28;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background: #1f2235;
    border: 1px solid #2a2d3e;
    selection-background-color: #2e3248;
    border-radius: 6px;
    color: #c8ccd8;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #2e3248;
    border: none;
    border-radius: 3px;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #363b58;
}

/* ══════════════════════════════
   PROGRESS BAR
══════════════════════════════ */
QProgressBar {
    background: #12141e;
    border: 1px solid #2a2d3e;
    border-radius: 6px;
    height: 10px;
    text-align: center;
    color: #7c8aaa;
    font-size: 8pt;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #5865a0, stop:1 #7c8fd4);
    border-radius: 5px;
}

/* ══════════════════════════════
   SCROLL
══════════════════════════════ */
QScrollBar:vertical {
    background: #12141e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #2e3248;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #3d4360; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #12141e;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #2e3248;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #3d4360; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ══════════════════════════════
   TEXT EDIT (LOG)
══════════════════════════════ */
QTextEdit {
    background: #0e1018;
    border: 1px solid #2a2d3e;
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "Fira Mono", "Courier New", monospace;
    font-size: 9pt;
    color: #9ba3ba;
    selection-background-color: #2e3248;
}

/* ══════════════════════════════
   LISTA / TABLA
══════════════════════════════ */
QListWidget, QTreeWidget, QTableWidget {
    background: #12141e;
    border: 1px solid #2a2d3e;
    border-radius: 8px;
    alternate-background-color: #161826;
    gridline-color: #2a2d3e;
}
QListWidget::item, QTableWidget::item {
    padding: 4px 8px;
    border-radius: 4px;
}
QListWidget::item:hover, QTableWidget::item:hover {
    background: #252840;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background: #2e3248;
    color: #e8ecf4;
}
QHeaderView::section {
    background: #1f2235;
    border: none;
    border-right: 1px solid #2a2d3e;
    border-bottom: 1px solid #2a2d3e;
    padding: 6px 10px;
    color: #7c8aaa;
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.05em;
}

/* ══════════════════════════════
   ETIQUETAS
══════════════════════════════ */
QLabel {
    background: transparent;
}
QLabel#label_title {
    font-size: 15pt;
    font-weight: 700;
    color: #e8ecf4;
    letter-spacing: -0.02em;
}
QLabel#label_subtitle {
    font-size: 9pt;
    color: #5a6080;
}
QLabel#label_hint {
    font-size: 8.5pt;
    color: #4a5070;
    font-style: italic;
}
QLabel#label_badge {
    background: #2e3248;
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 8pt;
    color: #7c8aaa;
}
QLabel#label_ok {
    color: #51cf66;
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

/* ══════════════════════════════
   SEPARADORES
══════════════════════════════ */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    background: #2a2d3e;
    border: none;
    max-height: 1px;
    max-width: 1px;
}

/* ══════════════════════════════
   TOOLTIP
══════════════════════════════ */
QToolTip {
    background: #2e3248;
    color: #c8ccd8;
    border: 1px solid #3b3f58;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 9.5pt;
}

/* ══════════════════════════════
   TAB
══════════════════════════════ */
QTabWidget::pane {
    border: 1px solid #2a2d3e;
    border-radius: 0 8px 8px 8px;
    background: #1a1d27;
}
QTabBar::tab {
    background: #12141e;
    border: 1px solid #2a2d3e;
    border-bottom: none;
    padding: 7px 18px;
    border-radius: 7px 7px 0 0;
    color: #7c8aaa;
    font-size: 9.5pt;
}
QTabBar::tab:selected {
    background: #1a1d27;
    color: #c8ccd8;
    border-bottom: 2px solid #5865a0;
}
QTabBar::tab:hover {
    color: #c8ccd8;
    background: #1f2235;
}

/* ══════════════════════════════
   SLIDER (selector de banda)
══════════════════════════════ */
QSlider::groove:horizontal {
    height: 4px;
    background: #2a2d3e;
    border-radius: 2px;
    margin: 2px 0;
}
QSlider::handle:horizontal {
    background: #5865a0;
    border: 2px solid #7c8fd4;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: #7c8fd4;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #4253a0, stop:1 #5865a0);
    border-radius: 2px;
}
"""
