"""ui/styles.py — QSS parametrizado por paleta de tema."""
from ui.theme import DARK


def get_qss(p: dict) -> str:
    chk  = p['chk_icon']
    dark = (p['name'] == 'dark')
    hover_tint = "rgba(255,255,255,0.05)" if dark else "rgba(0,0,0,0.05)"
    danger_bg  = "#3d1f2a" if dark else "#fde8e8"
    danger_bor = "#5a2a38" if dark else "#f0a0a0"
    danger_hov = "#4d2535" if dark else "#fdd0d0"

    return f"""
QWidget {{
    background-color: {p['bg_base']};
    color: {p['text']};
    font-family: "Inter", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 10pt;
}}

QMainWindow {{
    background-color: {p['bg_dark']};
}}

/* ══════ PANELES ══════ */
#sidebar {{
    background-color: {p['bg_dark']};
    border-right: 1px solid {p['border']};
}}

#panel_header {{
    background: {p['bg_panel']};
    border-bottom: 1px solid {p['border']};
    padding: 10px 16px;
    font-size: 11pt;
    font-weight: 600;
    color: {p['text']};
    border-radius: 8px 8px 0 0;
}}

QGroupBox {{
    background: transparent;
    border: 1px solid {p['border']};
    border-radius: 8px;
    margin-top: 22px;
    padding: 12px 8px 8px;
    font-size: 10pt;
    font-weight: 600;
    color: {p['text2']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 1px;
    padding: 0 6px;
    background: transparent;
    color: {p['text2']};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-size: 9pt;
}}

/* ══════ BOTONES ══════ */
QPushButton {{
    background: {p['border']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 10pt;
}}
QPushButton:hover {{
    background: {p['bg_panel']};
    border-color: {p['accent']};
    color: {p['text']};
}}
QPushButton:pressed {{
    background: {p['bg_dark']};
}}
QPushButton:disabled {{
    background: {p['bg_panel']};
    color: {p['text_muted']};
    border-color: {p['border']};
}}

QPushButton#btn_primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #5d70cc, stop:1 #4858b8);
    color: #ffffff;
    border: none;
    font-weight: 600;
    font-size: 10.5pt;
    padding: 9px 20px;
    border-radius: 9px;
}}
QPushButton#btn_primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #6d80dc, stop:1 #5868c8);
}}
QPushButton#btn_primary:disabled {{
    background: {p['border']};
    color: {p['text_muted']};
}}

QPushButton#btn_danger {{
    background: {danger_bg};
    color: #f87171;
    border: 1px solid {danger_bor};
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton#btn_danger:hover {{
    background: {danger_hov};
    border-color: #f87171;
}}

QPushButton#btn_icon {{
    background: transparent;
    border: none;
    padding: 4px 8px;
    border-radius: 6px;
    color: {p['text2']};
}}
QPushButton#btn_icon:hover {{
    background: {p['border']};
    color: {p['text']};
}}

/* ══════ INPUTS ══════ */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['bg_dark']};
    border: 1px solid {p['border2']};
    border-radius: 7px;
    padding: 6px 10px;
    color: {p['text']};
    selection-background-color: {p['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {p['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {p['text_muted']};
    background: {p['bg_panel']};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {p['bg_panel']};
    border: 1px solid {p['border']};
    selection-background-color: {p['border']};
    border-radius: 6px;
    color: {p['text']};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {p['border']};
    border: none;
    border-radius: 3px;
    width: 18px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {p['bg_panel']};
}}

/* ══════ PROGRESS BAR ══════ */
QProgressBar {{
    background: {p['bg_dark']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    height: 10px;
    text-align: center;
    color: {p['text2']};
    font-size: 8pt;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #4858b8, stop:1 #6070d0);
    border-radius: 5px;
}}

/* ══════ SCROLL ══════ */
QScrollBar:vertical {{
    background: {p['bg_dark']};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['border2']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {p['bg_dark']};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['border2']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ══════ TEXT EDIT (LOG) ══════ */
QTextEdit {{
    background: {p['bg_dark']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "Fira Mono", "Courier New", monospace;
    font-size: 9pt;
    color: {p['text2']};
    selection-background-color: {p['border']};
}}

/* ══════ LISTA / TABLA ══════ */
QListWidget, QTreeWidget, QTableWidget {{
    background: {p['bg_dark']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    alternate-background-color: {p['bg_base']};
    gridline-color: {p['border']};
}}
QListWidget::item, QTableWidget::item {{
    padding: 4px 8px;
    border-radius: 4px;
}}
QListWidget::item:hover, QTableWidget::item:hover {{
    background: {p['bg_panel']};
}}
QListWidget::item:selected, QTableWidget::item:selected {{
    background: {p['border']};
    color: {p['text']};
}}
QHeaderView::section {{
    background: {p['bg_panel']};
    border: none;
    border-right: 1px solid {p['border']};
    border-bottom: 1px solid {p['border']};
    padding: 6px 10px;
    color: {p['text2']};
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 0.05em;
}}

/* ══════ ETIQUETAS ══════ */
QLabel {{
    background: transparent;
}}
QLabel#label_title {{
    font-size: 15pt;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.02em;
}}
QLabel#label_subtitle {{
    font-size: 9.5pt;
    color: {p['text_muted']};
}}
QLabel#label_hint {{
    font-size: 10pt;
    color: {p['text_muted']};
}}
QLabel#label_badge {{
    background: {p['border']};
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 8.5pt;
    color: {p['text2']};
}}
QLabel#label_ok    {{ color: #4fd87a; font-weight: 600; }}
QLabel#label_warn  {{ color: #ffa94d; font-weight: 600; }}
QLabel#label_error {{ color: #f87171; font-weight: 600; }}

/* ══════ SEPARADORES ══════ */
QFrame[frameShape="4"] {{
    background: {p['border']};
    border: none;
    max-height: 1px;
}}
QFrame[frameShape="5"] {{
    background: {p['border']};
    border: none;
    max-width: 1px;
}}

/* ══════ TOOLTIP ══════ */
QToolTip {{
    background: {p['bg_panel']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 9.5pt;
}}

/* ══════ TAB ══════ */
QTabWidget::pane {{
    border: 1px solid {p['border']};
    border-radius: 0 8px 8px 8px;
    background: {p['bg_base']};
}}
QTabBar::tab {{
    background: {p['bg_dark']};
    border: 1px solid {p['border']};
    border-bottom: none;
    padding: 8px 22px;
    border-radius: 7px 7px 0 0;
    color: {p['text2']};
    font-size: 10pt;
}}
QTabBar::tab:selected {{
    background: {p['bg_base']};
    color: {p['text']};
    border-bottom: 2px solid {p['accent']};
}}
QTabBar::tab:hover {{
    color: {p['text']};
    background: {p['bg_panel']};
}}

/* ══════ SLIDER ══════ */
QSlider::groove:horizontal {{
    height: 4px;
    background: {p['border']};
    border-radius: 2px;
    margin: 2px 0;
}}
QSlider::handle:horizontal {{
    background: {p['accent']};
    border: 2px solid #8090e0;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{ background: #8090e0; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #4858b8, stop:1 #6070d0);
    border-radius: 2px;
}}

/* ══════ RADIO / CHECKBOX ══════ */
QRadioButton, QCheckBox {{
    color: {p['text']};
    spacing: 8px;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p['border2']};
    border-radius: 4px;
    background: {p['bg_dark']};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QRadioButton::indicator:checked {{
    background: {p['accent']};
    border-color: #8090e0;
}}
QCheckBox::indicator:checked {{
    background: {p['accent']};
    border-color: #8090e0;
    image: url("{chk}");
}}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
    border-color: {p['accent']};
}}

/* ══════ SPLITTER ══════ */
QSplitter::handle {{ background: {p['border']}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical   {{ height: 2px; }}

/* ══════ DOCK ══════ */
QDockWidget {{
    color: {p['text']};
    font-size: 9.5pt;
}}
QDockWidget::title {{
    background: {p['bg_panel']};
    padding: 4px 8px;
    border-bottom: 1px solid {p['border']};
}}

/* ══════ RIBBON ══════ */
QWidget#ribbon_tab_bar {{
    background: {p['rb_tabs']};
}}
QLabel#ribbon_logo {{
    color: {p['accent']};
    font-size: 13pt;
    background: transparent;
    padding: 0 10px 0 6px;
    border: none;
}}
QToolButton#ribbon_tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {p['rb_hint']};
    font-size: 9.5pt;
    font-family: 'Segoe UI', Inter, sans-serif;
    padding: 5px 16px 3px 16px;
    min-width: 60px;
}}
QToolButton#ribbon_tab:checked {{
    color: {p['text']};
    border-bottom: 2px solid {p['accent']};
    background: {p['rb_panel']};
}}
QToolButton#ribbon_tab:hover:!checked {{
    color: {p['text2']};
    background: {hover_tint};
}}
QFrame#ribbon_sep {{
    background: {p['border']};
    border: none;
    max-height: 1px;
}}
QStackedWidget#ribbon_stack, QWidget#ribbon_panel {{
    background: {p['rb_panel']};
}}
QWidget#ribbon_vsep {{
    background: {p['rb_sep']};
}}
QLabel#ribbon_group_lbl {{
    color: {p['rb_grp_lbl']};
    font-size: 8pt;
    background: transparent;
}}
QWidget#ribbon_panel QLabel {{
    color: {p['rb_hint']};
    background: transparent;
    font-size: 9pt;
    font-family: 'Segoe UI', Inter, sans-serif;
}}
QWidget#ribbon_panel QToolButton {{
    background: transparent;
    border: none;
    border-radius: 5px;
    color: {p['rb_icon']};
    font-size: 9pt;
    font-family: 'Segoe UI', Inter, sans-serif;
    padding: 4px 2px 0 2px;
}}
QWidget#ribbon_panel QToolButton:hover {{
    background: {p['rb_btn_bg']};
    color: {p['text']};
}}
QWidget#ribbon_panel QToolButton:pressed {{
    background: {p['bg_dark']};
}}
QWidget#ribbon_panel QToolButton:disabled {{
    color: {p['rb_disabled']};
}}
QWidget#ribbon_panel QLineEdit {{
    background: {p['rb_btn_bg']};
    border: 1px solid {p['rb_btn_bor']};
    border-radius: 3px;
    color: {p['text']};
    font-size: 9pt;
    font-family: 'Segoe UI', Inter, sans-serif;
    padding: 2px 4px;
    min-height: 18px;
}}
QWidget#ribbon_panel QComboBox {{
    background: {p['rb_btn_bg']};
    border: 1px solid {p['rb_btn_bor']};
    border-radius: 3px;
    color: {p['text']};
    font-size: 9pt;
    font-family: 'Segoe UI', Inter, sans-serif;
    padding: 2px 4px;
    min-height: 18px;
}}
QWidget#ribbon_panel QComboBox::drop-down {{
    border: none;
    width: 14px;
}}
QWidget#ribbon_panel QComboBox QAbstractItemView {{
    background: {p['bg_panel']};
    border: 1px solid {p['border']};
    color: {p['text']};
    selection-background-color: {p['border']};
}}
QWidget#ribbon_panel QCheckBox {{
    color: {p['text']};
    font-size: 9pt;
    font-family: 'Segoe UI', Inter, sans-serif;
    spacing: 5px;
    background: transparent;
}}
QWidget#ribbon_panel QCheckBox::indicator {{
    width: 13px; height: 13px;
    border: 1px solid {p['rb_btn_bor']};
    border-radius: 3px;
    background: {p['rb_btn_bg']};
}}
QWidget#ribbon_panel QCheckBox::indicator:checked {{
    background: {p['accent']};
    border-color: #8090e0;
    image: url("{chk}");
}}
QWidget#ribbon_panel QCheckBox::indicator:hover {{
    border-color: {p['accent']};
}}
QToolButton#ribbon_theme_toggle {{
    background: transparent;
    border: none;
    color: {p['rb_icon']};
    font-size: 11pt;
    padding: 0 10px;
    border-radius: 4px;
}}
QToolButton#ribbon_theme_toggle:hover {{
    background: {p['rb_btn_bg']};
    color: {p['text']};
}}
"""


QSS = get_qss(DARK)
