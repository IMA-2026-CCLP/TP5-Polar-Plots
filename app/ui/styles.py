"""ui/styles.py — QSS parametrizado por paleta de tema."""
from ui.theme import LIGHT


def get_qss(p: dict) -> str:
    chk  = p['chk_icon']
    dark = (p['name'] == 'dark')
    hover_tint = "rgba(255,255,255,0.05)" if dark else "rgba(0,0,0,0.05)"
    danger_bg  = "#3d1f2a" if dark else "#fde8e8"
    danger_bor = "#5a2a38" if dark else "#f0a0a0"
    danger_hov = "#4d2535" if dark else "#fdd0d0"
    font_body  = p.get('font_body', 'IBM Plex Sans')
    font_mono  = p.get('font_mono', 'IBM Plex Mono')

    return f"""
QWidget {{
    background-color: {p['bg_base']};
    color: {p['text']};
    font-family: "{font_body}", "Segoe UI", sans-serif;
    font-size: 9pt;
}}

QLabel#label_mono, QLineEdit#field_mono {{
    font-family: "{font_mono}", "Consolas", monospace;
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
    font-size: 10pt;
    font-weight: 600;
    color: {p['text']};
    border-radius: 2px 8px 0 0;
}}

QGroupBox {{
    background: transparent;
    border: 1px solid {p['border']};
    border-radius: 2px;
    margin-top: 9px;
    padding: 12px 6px 6px;
    font-size: 9pt;
    font-weight: 600;
    color: {p['text2']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    background: {p['bg_base']};
    color: {p['text2']};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-size: 9pt;
}}

/* ══════ BOTONES ══════ */
QPushButton, QToolButton {{
    background: {p['btn_bg']};
    color: {p['btn_text']};
    border: 1px solid {p['btn_border']};
    border-radius: 2px;
    padding: 3px 10px;
    font-size: 9pt;
}}
QPushButton:hover, QToolButton:hover {{
    background: {p['btn_hover']};
    border-color: {p['accent']};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {p['btn_border']};
}}
QPushButton:disabled, QToolButton:disabled {{
    background: {p['bg_panel']};
    color: {p['text_muted']};
    border-color: {p['border']};
}}

QPushButton#btn_primary {{
    background: {p['btn_bg']};
    color: {p['btn_text']};
    border: 1px solid {p['btn_border']};
    font-weight: 600;
    font-size: 9pt;
    padding: 3px 14px;
    border-radius: 2px;
}}
QPushButton#btn_primary:hover {{
    background: {p['btn_hover']};
    color: {p['btn_text']};
}}
QPushButton#btn_primary:disabled {{
    background: {p['border']};
    color: {p['text_muted']};
    border-color: {p['border']};
}}

QPushButton#btn_danger {{
    background: {danger_bg};
    color: #f87171;
    border: 1px solid {danger_bor};
    border-radius: 2px;
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
    border-radius: 2px;
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
    border-radius: 2px;
    padding: 2px 6px;
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
    selection-background-color: {p['accent']};
    selection-color: #ffffff;
    border-radius: 2px;
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
    border-radius: 2px;
    height: 10px;
    text-align: center;
    color: {p['text2']};
    font-size: 8pt;
}}
QProgressBar::chunk {{
    background: {p['accent']};
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
    border-radius: 2px;
    padding: 8px;
    font-family: "{font_mono}", "Consolas", monospace;
    font-size: 9pt;
    color: {p['text2']};
    selection-background-color: {p['border']};
}}

/* ══════ LISTA / TABLA ══════ */
QListWidget, QTreeWidget, QTableWidget {{
    background: {p['bg_dark']};
    border: 1px solid {p['border']};
    border-radius: 2px;
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
    padding: 2px 6px;
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
    font-size: 9pt;
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
    border-radius: 2px;
    padding: 5px 9px;
    font-size: 9.5pt;
}}

/* ══════ TAB ══════ */
QTabWidget::pane {{
    border: 1px solid {p['border']};
    border-radius: 2px;
    background: {p['bg_base']};
}}
QTabBar::tab {{
    background: {p['bg_dark']};
    border: 1px solid {p['border']};
    border-bottom: none;
    padding: 8px 22px;
    border-radius: 2px;
    color: {p['text2']};
    font-size: 9pt;
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
    border: 2px solid {p['accent']};
    width: 14px;
    height: 14px;
    border-radius: 2px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{ background: {p['accent']}; }}
QSlider::sub-page:horizontal {{
    background: {p['accent']};
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
    border-color: {p['accent']};
}}
QCheckBox::indicator:checked {{
    background: {p['accent']};
    border-color: {p['accent']};
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
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {p['bg_dark']};
    text-align: center;
    padding: 2px 6px;
    border: 1px solid {p['border2']};
}}

/* ══════ BARRA SUPERIOR (native_ribbon.py) ══════ */
QMenuBar {{ background: {p['bg_base']}; padding: 0; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {p['accent_soft']}; }}
QMenu {{ background: {p['bg_panel']}; border: 1px solid {p['border2']}; padding: 2px; }}
QMenu::item {{ padding: 4px 26px 4px 22px; }}
QMenu::item:selected {{ background: {p['accent']}; color: {p['accent_ink']}; }}
QMenu::item:disabled {{ color: {p['text_muted']}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 3px 6px; }}
QTabBar#main_tabs::tab {{
    background: {p['bg_dark']}; border: 1px solid {p['border2']}; border-bottom: none;
    padding: 4px 16px; margin-right: 2px; border-radius: 0; color: {p['text2']}; font-size: 9pt;
}}
QTabBar#main_tabs::tab:selected {{
    background: {p['bg_base']}; color: {p['text']}; border-bottom: none; font-weight: 600;
}}
QTabBar#main_tabs::tab:!selected {{ margin-top: 2px; }}
QFrame#rb_line {{ background: {p['border2']}; }}
QFrame#rb_sep  {{ background: {p['border2']}; }}
QLabel#rb_cap  {{ color: {p['text_muted']}; font-weight: 600; }}
QLabel#rb_chip {{ color: {p['text2']}; padding-right: 4px; }}
QLabel#rb_status {{ color: {p['text_muted']}; }}
QToolButton#rb_info {{ padding: 0; font-weight: 700; font-style: italic; border-radius: 11px; }}
QPushButton#pill {{ padding: 2px 10px; }}
QPushButton#pill:checked {{
    background: {p['accent_soft']}; border-color: {p['accent']}; color: {p['accent']}; font-weight: 600;
}}

"""


QSS = get_qss(LIGHT)
