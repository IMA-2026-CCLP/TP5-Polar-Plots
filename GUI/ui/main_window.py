"""
ui/main_window.py — Ventana principal con QStackedWidget (Configuración | Resultados)
"""
import os, json
import numpy as np
from pathlib import Path
# from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, QDockWidget,
    QGroupBox, QComboBox, QCheckBox, QProgressBar,
    QTextEdit, QSplitter, QFrame, QDoubleSpinBox, QScrollArea,
    QSpinBox, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSettings, QSize, pyqtSlot
from PyQt6.QtGui import QFont, QTextCursor

from core.scanner  import scan_folder, get_grid_info, template_preview, AudioFile
from core.worker   import ProcessWorker
from core.data_store import load_polar, freq_label, ISO_BANDS_HZ, ISO_BANDS_OCTAVE

from ui.styles        import QSS
from ui.band_selector import BandSelectorWidget
from ui.band_filter   import BandFilterWidget
from ui.balloon_view  import BalloonView
from ui.polar_plot_2d import PolarPlot2D

from plot.balloon import COLORSCALES


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Polar Pattern Analyzer")
        self.setMinimumSize(1200, 750)
        self.resize(1440, 860)
        self.setStyleSheet(QSS)

        self._files:   list[AudioFile] = []
        self._polar:   dict  = {}
        self._worker:  ProcessWorker | None = None
        self._settings = QSettings("AcousticTools", "PolarAnalyzer")

        self._build_ui()
        self._restore_settings()

    # ════════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── Top bar fija ──────────────────────────────────────────────────
        top_bar = self._make_top_bar()

        # ── Central: QStackedWidget ───────────────────────────────────────
        self.stacked = QStackedWidget()
        
        # Screen 0: Configuración
        config_screen = self._make_config_screen()
        self.stacked.addWidget(config_screen)
        
        # Screen 1: Resultados
        results_screen = self._make_results_screen()
        self.stacked.addWidget(results_screen)

        self.stacked.setCurrentIndex(0)
        # Show/hide top back button depending on current screen
        self.stacked.currentChanged.connect(lambda idx: self.btn_back_top.setVisible(idx == 1))

        # ── Layout principal ──────────────────────────────────────────────
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(top_bar)
        main_layout.addWidget(self.stacked, 1)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # ── Dock Log (estirable y desprendible) ───────────────────────────
        self._setup_log_dock()

        # ── Menú Superior ─────────────────────────────────────────────────
        self._setup_menu_bar()

        # ── Status bar ────────────────────────────────────────────────────
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background: #12141e;
                border-top: 1px solid #2a2d3e;
                color: #5a6080;
                font-size: 8.5pt;
                padding: 0 12px;
            }
        """)
        self.statusBar().showMessage("Listo.")

    # ────────────────────────────────────────────────────────────────────
    # TOP BAR
    # ────────────────────────────────────────────────────────────────────

    def _make_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(56)
        bar.setStyleSheet("""
            QWidget {
                background: #12141e;
                border-bottom: 1px solid #2a2d3e;
            }
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        dot = QLabel("⬡")
        dot.setStyleSheet("color:#5865a0; font-size:18pt; background:transparent; border:none;")
        lay.addWidget(dot)

        lbl = QLabel("Polar Pattern Analyzer")
        lbl.setObjectName("label_title")
        lbl.setStyleSheet("font-size:14pt; font-weight:700; color:#e8ecf4; background:transparent; border:none;")
        lay.addWidget(lbl)
        
        lay.addStretch()

        btn_open = QPushButton("  Abrir NPZ...")
        btn_open.setObjectName("btn_icon")
        btn_open.setStyleSheet("""
            QPushButton {
                background:#1f2235; border:1px solid #2a2d3e;
                border-radius:7px; color:#7c8aaa;
                padding: 6px 14px; font-size:9.5pt;
            }
            QPushButton:hover { background:#2a2d3e; color:#c8ccd8; }
        """)
        btn_open.clicked.connect(self._action_open_npz)
        lay.addWidget(btn_open)

        return bar

    # ────────────────────────────────────────────────────────────────────
    # SCREEN 0: CONFIGURATION
    # ────────────────────────────────────────────────────────────────────

    def _make_config_screen(self) -> QWidget:
        screen = QWidget()
        lay = QVBoxLayout(screen)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Scroll area con controles
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container_lay = QVBoxLayout(container)
        container_lay.setContentsMargins(20, 20, 20, 20)
        container_lay.setSpacing(16)

        container_lay.addWidget(self._make_group_folder())
        container_lay.addWidget(self._make_group_template())
        container_lay.addWidget(self._make_group_output())
        container_lay.addWidget(self._make_group_process())
        container_lay.addStretch()

        scroll.setWidget(container)
        lay.addWidget(scroll, 1)

        return screen

    def _make_group_folder(self) -> QGroupBox:
        g = QGroupBox("CARPETA DE AUDIOS")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        row = QHBoxLayout()
        self.le_folder = QLineEdit()
        self.le_folder.setPlaceholderText("Seleccioná la carpeta con los archivos de audio…")
        self.le_folder.setReadOnly(True)
        row.addWidget(self.le_folder)

        btn = QPushButton("📂")
        # btn.setFixedWidth(36)
        btn.clicked.connect(self._action_choose_folder)
        row.addWidget(btn)
        lay.addLayout(row)

        self.lbl_folder_info = QLabel("")
        self.lbl_folder_info.setObjectName("label_hint")
        self.lbl_folder_info.setWordWrap(True)
        lay.addWidget(self.lbl_folder_info)

        return g

    def _make_group_template(self) -> QGroupBox:
        g = QGroupBox("NOMENCLATURA DE ARCHIVOS")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        lbl_hint = QLabel(
            "Usá <b>{H}</b> para azimut y <b>{V}</b> para elevación.<br>"
            "Ej: <code>audio_{H:03d}_{V:03d}.wav</code>"
        )
        lbl_hint.setStyleSheet("color:#5a6080; font-size:9pt; background:transparent;")
        lbl_hint.setWordWrap(True)
        lay.addWidget(lbl_hint)

        self.le_template = QLineEdit()
        self.le_template.setPlaceholderText("audio_{H:03d}_{V:03d}.wav")
        self.le_template.setText("audio_{H:03d}_{V:03d}.wav")
        self.le_template.textChanged.connect(self._on_template_changed)
        lay.addWidget(self.le_template)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Vista previa:"))
        self.lbl_preview = QLabel()
        self.lbl_preview.setStyleSheet("color:#7c8aaa; font-family:monospace; background:transparent;")
        row2.addWidget(self.lbl_preview, 1)
        lay.addLayout(row2)

        self.lbl_match_status = QLabel("")
        self.lbl_match_status.setWordWrap(True)
        lay.addWidget(self.lbl_match_status)

        btn_scan = QPushButton("🔍  Escanear carpeta")
        btn_scan.clicked.connect(self._action_scan)
        lay.addWidget(btn_scan)

        self._on_template_changed(self.le_template.text())
        return g

    def _make_group_output(self) -> QGroupBox:
        g = QGroupBox("ARCHIVO DE SALIDA (.NPZ)")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)

        row = QHBoxLayout()
        self.le_output = QLineEdit()
        self.le_output.setPlaceholderText("patron_polar.npz")
        self.le_output.setText("patron_polar_GUI_v3.npz")
        row.addWidget(self.le_output)
        btn = QPushButton("💾")
        # btn.setFixedWidth(36)
        btn.clicked.connect(self._action_choose_output)
        row.addWidget(btn)
        lay.addLayout(row)

        return g    

    def _make_group_process(self) -> QGroupBox:
        g = QGroupBox("Selección de bandas")
        lay = QVBoxLayout(g)
        lay.setSpacing(12)

        # ─── FILA 1: Resolución y Modo ───────────────────────────
        row_selectores = QHBoxLayout()
        
        # Selector de tipo de banda
        lay_tipo = QVBoxLayout()
        lay_tipo.addWidget(QLabel("Resolución:"))
        self.cb_tipo_banda = QComboBox()
        self.cb_tipo_banda.addItems(["Por Octava", "Por Tercio de Octava"])
        self.cb_tipo_banda.currentTextChanged.connect(self._on_tipo_banda_changed)
        lay_tipo.addWidget(self.cb_tipo_banda)
        row_selectores.addLayout(lay_tipo, 1)

        # Selector de modo de procesamiento
        lay_modo = QVBoxLayout()
        lay_modo.addWidget(QLabel("Modo:"))
        self.cb_modo_seleccion = QComboBox()
        self.cb_modo_seleccion.addItems(["Rango (Mín/Máx)", "Personalizada"])
        self.cb_modo_seleccion.currentTextChanged.connect(self._on_modo_seleccion_changed)
        lay_modo.addWidget(self.cb_modo_seleccion)
        row_selectores.addLayout(lay_modo, 1)

        lay.addLayout(row_selectores)

        # ─── FILA 2A: Contenedor de Rango (Mínimo y Máximo) ──────
        self.rango_container = QWidget()
        lay_rango = QHBoxLayout(self.rango_container)
        lay_rango.setContentsMargins(0, 0, 0, 0)
        lay_rango.setSpacing(12)

        lay_min = QVBoxLayout()
        lay_min.addWidget(QLabel("Banda Mínima:"))
        self.cb_banda_min = QComboBox()
        lay_min.addWidget(self.cb_banda_min)
        lay_rango.addLayout(lay_min)

        lay_max = QVBoxLayout()
        lay_max.addWidget(QLabel("Banda Máxima:"))
        self.cb_banda_max = QComboBox()
        lay_max.addWidget(self.cb_banda_max)
        lay_rango.addLayout(lay_max)

        lay.addWidget(self.rango_container)

        # ─── FILA 2B: Control Personalizado (Checkboxes) ─────────
        self.band_filter = BandFilterWidget()
        lay.addWidget(self.band_filter)
        
        # Ocultamos la vista personalizada por defecto (arranca en Rango)
        self.band_filter.setVisible(False)

        # Inicializamos los valores por defecto (ej: Tercios de octava)
        # Importante: llamamos a esto para popular los selectores por primera vez
        self._on_tipo_banda_changed("Por Tercio de Octava")
        self.cb_tipo_banda.setCurrentText("Por Tercio de Octava")

        # ─── FILA 3: Botones de Acción y Progreso ────────────────
        self.btn_process = QPushButton("▶  Procesar audios")
        self.btn_process.setObjectName("btn_primary")
        self.btn_process.setEnabled(False)
        self.btn_process.clicked.connect(self._action_process)
        lay.addWidget(self.btn_process)

        self.btn_cancel = QPushButton("✕  Cancelar")
        self.btn_cancel.setObjectName("btn_danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._action_cancel)
        lay.addWidget(self.btn_cancel)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        lay.addWidget(self.progress_bar)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("label_hint")
        self.lbl_progress.setVisible(False)
        lay.addWidget(self.lbl_progress)

        return g

    # ────────────────────────────────────────────────────────────────────
    # SCREEN 1: RESULTS
    # ────────────────────────────────────────────────────────────────────

    def _make_results_screen(self) -> QWidget:
        screen = QWidget()
        lay = QVBoxLayout(screen)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header con info del dataset
        header = self._make_results_header()
        lay.addWidget(header)

        # Splitter: plot | stats panel
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("QSplitter::handle { background:#2a2d3e; }")

        # Lado izquierdo: toolbar + plot + band selector
        left_panel = self._make_plot_panel()
        
        # Lado derecho: stats y exportación (make instance attribute for toggling)
        # self.right_panel = self._make_stats_panel()
        # self.right_panel.setMinimumWidth(180)
        # self.right_panel.setMaximumWidth(350)

        splitter.addWidget(left_panel)
        # splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1100, 280])
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        lay.addWidget(splitter, 1)

        # Bottom bar
        bottom = self._make_results_bottom_bar()
        lay.addWidget(bottom)

        return screen

    def _make_results_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("""
            QWidget {
                background: #1f2235;
                border-bottom: 1px solid #2a2d3e;
            }
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(14, 0, 14, 0)

        # Back to config button (colored, hidden on config screen)
        self.btn_back_top = QPushButton("◀ Volver")
        self.btn_back_top.setObjectName("btn_back_top")
        self.btn_back_top.setStyleSheet("""
            QPushButton {
                background: #4253a0;
                color: white;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 700;
                font-size: 9.5pt;
            }
            QPushButton:hover { background: #ff8787; }
        """)
        self.btn_back_top.setVisible(False)
        self.btn_back_top.clicked.connect(lambda: self.stacked.setCurrentIndex(0))
        lay.addWidget(self.btn_back_top)


        self.lbl_header_filename = QLabel("—")
        self.lbl_header_filename.setStyleSheet("color:#e8ecf4; font-weight:700; font-size:11pt;")
        lay.addWidget(self.lbl_header_filename)

        lay.addSpacing(20)

        self.lbl_header_fs = QLabel("Fs: — Hz")
        self.lbl_header_fs.setStyleSheet("color:#7c8aaa;")
        lay.addWidget(self.lbl_header_fs)

        self.lbl_header_shape = QLabel("Shape: —")
        self.lbl_header_shape.setStyleSheet("color:#7c8aaa;")
        lay.addWidget(self.lbl_header_shape)

        lay.addStretch()

        # Exportación
        self.btn_export_csv = QPushButton("📊 Exportar CSV")
        self.btn_export_csv.setObjectName("btn_icon")
        self.btn_export_csv.clicked.connect(self._action_export_csv)
        lay.addWidget(self.btn_export_csv)

        self.btn_export_img = QPushButton("🖼️  Exportar Imagen")
        self.btn_export_img.setObjectName("btn_icon")
        self.btn_export_img.clicked.connect(self._action_export_image)
        lay.addWidget(self.btn_export_img)

        self.btn_export_npz = QPushButton("💾 Descargar NPZ")
        self.btn_export_npz.setObjectName("btn_icon")
        self.btn_export_npz.clicked.connect(self._action_export_npz)
        lay.addWidget(self.btn_export_npz)

        lay.addSpacing(10)

        return header

    def _make_plot_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar
        toolbar = self._make_viz_toolbar()
        lay.addWidget(toolbar)

        # Splitter para 3D + 2D plots
        plot_splitter = QSplitter(Qt.Orientation.Horizontal)
        plot_splitter.setHandleWidth(2)
        plot_splitter.setStyleSheet("QSplitter::handle { background:#2a2d3e; }")

        # Balloon view 3D
        self.balloon_view = BalloonView()
        self.balloon_view.point_hovered.connect(self._on_point_hovered)
        self.balloon_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Polar plot 2D
        self.polar_2d = PolarPlot2D()
        self.polar_2d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        plot_splitter.addWidget(self.balloon_view)
        plot_splitter.addWidget(self.polar_2d)
        plot_splitter.setStretchFactor(0, 1)
        plot_splitter.setStretchFactor(1, 1)
        plot_splitter.setSizes([500, 400])

        lay.addWidget(plot_splitter, 1)

        # Band selector 
        band_bar = self._make_band_bar()
        lay.addWidget(band_bar)

        return w

    def _make_viz_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet("""
            QWidget {
                background:#1f2235;
                border-bottom:1px solid #2a2d3e;
            }
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(14)

        lay.addWidget(QLabel("Colorscale:"))
        self.cb_colorscale = QComboBox()
        self.cb_colorscale.addItems(list(COLORSCALES.keys()))
        self.cb_colorscale.setCurrentText("Plasma")
        # self.cb_colorscale.setFixedWidth(110)
        self.cb_colorscale.currentTextChanged.connect(
            lambda t: self.balloon_view.set_colorscale(t)
        )
        lay.addWidget(self.cb_colorscale)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("background:#2a2d3e; max-width:1px;")
        lay.addWidget(sep)

        self.chk_normalize = QCheckBox("Normalizar radio")
        self.chk_normalize.setChecked(True)
        self.chk_normalize.stateChanged.connect(
            lambda s: self.balloon_view.set_normalize(s == 2)
        )
        lay.addWidget(self.chk_normalize)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet("background:#2a2d3e; max-width:1px;")
        lay.addWidget(sep3)

        lay.addWidget(QLabel("Simetría:"))
        self.cb_symmetry = QComboBox()
        self.cb_symmetry.addItems(["Ninguna", "Azimut", "Elevación", "Ambas"])
        self.cb_symmetry.setCurrentText("Ninguna")
        # self.cb_symmetry.setFixedWidth(100)
        self.cb_symmetry.currentTextChanged.connect(self._on_symmetry_changed)
        lay.addWidget(self.cb_symmetry)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("background:#2a2d3e; max-width:1px;")
        lay.addWidget(sep2)

        self.chk_fix_range = QCheckBox("Rango dB fijo:")
        self.chk_fix_range.setChecked(False)
        self.chk_fix_range.stateChanged.connect(self._on_fix_range_changed)
        lay.addWidget(self.chk_fix_range)

        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-200, 200)
        self.spin_min.setValue(-20)
        self.spin_min.setSuffix(" dB")
        # self.spin_min.setFixedWidth(90)
        self.spin_min.setEnabled(False)
        self.spin_min.valueChanged.connect(self._on_spin_range_changed)
        lay.addWidget(self.spin_min)

        lay.addWidget(QLabel("→"))

        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-200, 200)
        self.spin_max.setValue(5)
        self.spin_max.setSuffix(" dB")
        # self.spin_max.setFixedWidth(90)
        self.spin_max.setEnabled(False)
        self.spin_max.valueChanged.connect(self._on_spin_range_changed)
        lay.addWidget(self.spin_max)

        sep_toggle = QFrame()
        sep_toggle.setFrameShape(QFrame.Shape.VLine)
        sep_toggle.setStyleSheet("background:#2a2d3e; max-width:1px;")
        lay.addWidget(sep_toggle)

        # Plot visibility toggles
        # self.btn_toggle_stats = QPushButton("📊")
        # self.btn_toggle_stats.setCheckable(True)
        # self.btn_toggle_stats.setChecked(True)
        # # self.btn_toggle_stats.setFixedWidth(40)
        # self.btn_toggle_stats.setToolTip("Mostrar/ocultar panel de estadísticas")
        # self.btn_toggle_stats.clicked.connect(lambda s: self._toggle_stats_panel(s))
        # lay.addWidget(self.btn_toggle_stats)

        self.btn_3d = QPushButton("3D")
        self.btn_3d.setCheckable(True)
        self.btn_3d.setChecked(True)
        # self.btn_3d.setFixedWidth(44)
        self.btn_3d.setToolTip("Mostrar solo gráfico 3D")
        self.btn_3d.clicked.connect(lambda s: self._set_plot_mode("3d", s))
        lay.addWidget(self.btn_3d)

        self.btn_2d = QPushButton("2D")
        self.btn_2d.setCheckable(True)
        self.btn_2d.setChecked(False)
        # self.btn_2d.setFixedWidth(44)
        self.btn_2d.setToolTip("Mostrar solo gráfico 2D")
        self.btn_2d.clicked.connect(lambda s: self._set_plot_mode("2d", s))
        lay.addWidget(self.btn_2d)

        lay.addStretch()

        self.lbl_hover = QLabel("hover: —")
        self.lbl_hover.setStyleSheet("color:#7c8aaa; font-size:9pt; background:transparent; border:none;")
        lay.addWidget(self.lbl_hover)

        return bar

    def _make_band_bar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("""
            QWidget {
                background:#1f2235;
                border-top:1px solid #2a2d3e;
            }
        """)
        lay = QHBoxLayout(w)
        # lay.setContentsMargins(14, 10, 14, 10)

        self.band_selector = BandSelectorWidget()
        self.band_selector.band_changed.connect(self._on_band_changed)
        self.band_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.band_selector)

        return w

    def _make_stats_panel(self) -> QWidget: # NO SE ESTA USANDO
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # Exportación
        self.btn_export_csv = QPushButton("📊 Exportar CSV")
        self.btn_export_csv.setObjectName("btn_icon")
        self.btn_export_csv.clicked.connect(self._action_export_csv)
        lay.addWidget(self.btn_export_csv)

        self.btn_export_img = QPushButton("🖼️  Exportar Imagen")
        self.btn_export_img.setObjectName("btn_icon")
        self.btn_export_img.clicked.connect(self._action_export_image)
        lay.addWidget(self.btn_export_img)

        self.btn_export_npz = QPushButton("💾 Descargar NPZ")
        self.btn_export_npz.setObjectName("btn_icon")
        self.btn_export_npz.clicked.connect(self._action_export_npz)
        lay.addWidget(self.btn_export_npz)

        lay.addSpacing(10)

        # Estadísticas del dataset
        stats_box = QGroupBox("DATASET")
        stats_lay = QVBoxLayout(stats_box)
        stats_lay.setSpacing(6)

        self.lbl_n_files = QLabel("Archivos: —")
        self.lbl_n_files.setStyleSheet("color:#c8ccd8; font-size:9pt;")
        stats_lay.addWidget(self.lbl_n_files)

        self.lbl_grid = QLabel("Grilla: —")
        self.lbl_grid.setStyleSheet("color:#c8ccd8; font-size:9pt;")
        stats_lay.addWidget(self.lbl_grid)

        self.lbl_az_range = QLabel("Azimut: —")
        self.lbl_az_range.setStyleSheet("color:#c8ccd8; font-size:9pt;")
        stats_lay.addWidget(self.lbl_az_range)

        self.lbl_el_range = QLabel("Elevación: —")
        self.lbl_el_range.setStyleSheet("color:#c8ccd8; font-size:9pt;")
        stats_lay.addWidget(self.lbl_el_range)

        lay.addWidget(stats_box)

        # Estadísticas por banda
        bands_box = QGroupBox("BANDAS")
        bands_lay = QVBoxLayout(bands_box)
        bands_lay.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(200)

        self.bands_stats_container = QWidget()
        self.bands_stats_lay = QVBoxLayout(self.bands_stats_container)
        self.bands_stats_lay.setContentsMargins(4, 4, 4, 4)
        self.bands_stats_lay.setSpacing(2)
        self.bands_stats_lay.addStretch()

        scroll.setWidget(self.bands_stats_container)
        bands_lay.addWidget(scroll)

        lay.addWidget(bands_box)
        lay.addStretch()

        return panel

    def _make_results_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setStyleSheet("""
            QWidget {
                background: #1f2235;
                border-top: 1px solid #2a2d3e;
            }
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)

        lay.addStretch()

        self.lbl_bottom_info = QLabel("")
        self.lbl_bottom_info.setStyleSheet("color:#7c8aaa; font-size:9pt;")
        lay.addWidget(self.lbl_bottom_info)

        return bar

    # ────────────────────────────────────────────────────────────────────
    # LOG DOCK
    # ────────────────────────────────────────────────────────────────────

    def _setup_log_dock(self):
        self.log_dock = QDockWidget("Log")
        self.log_dock.setObjectName("LogDock")
        self.log_dock.setMinimumHeight(100)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("""
            QTextEdit {
                background: #12141e;
                color: #c8ccd8;
                border: 1px solid #2a2d3e;
                font-family: monospace;
                font-size: 8.5pt;
            }
        """)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        toolbar = QWidget()
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(4, 4, 4, 4)
        btn_clear = QPushButton("Limpiar")
        btn_clear.setObjectName("btn_icon")
        btn_clear.setMaximumWidth(80)
        btn_clear.clicked.connect(self.log_edit.clear)
        tb_lay.addStretch()
        tb_lay.addWidget(btn_clear)
        lay.addWidget(toolbar)

        lay.addWidget(self.log_edit, 1)
        self.log_dock.setWidget(container)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()


    # ────────────────────────────────────────────────────────────────────
    # MENU BAR
    # ────────────────────────────────────────────────────────────────────
    def _setup_menu_bar(self):
        menu_bar = self.menuBar()
        
        # Estilizamos el menú para que combine con el tema oscuro de la app
        menu_bar.setStyleSheet("""
            QMenuBar {
                background: #12141e;
                color: #e8ecf4;
                border-bottom: 1px solid #2a2d3e;
                padding: 2px;
            }
            QMenuBar::item:selected {
                background: #2a2d3e;
                border-radius: 4px;
            }
            QMenu {
                background: #1f2235;
                color: #c8ccd8;
                border: 1px solid #2a2d3e;
            }
            QMenu::item {
                padding: 6px 24px 6px 24px;
            }
            QMenu::item:selected {
                background: #5865a0;
                color: white;
            }
        """)

        # Crear el menú desplegable "Ver"
        menu_ver = menu_bar.addMenu("Ver")

        # La magia del QDockWidget: ya trae una acción para mostrar/ocultar
        action_log = self.log_dock.toggleViewAction()
        action_log.setText("Consola de eventos (Log)")
        action_log.setShortcut("Ctrl+L") # Le agregamos un atajo de teclado rápido
        
        # Agregamos la acción al menú
        menu_ver.addAction(action_log)


    # ════════════════════════════════════════════════════════════════════
    # SLOTS / ACTIONS
    # ════════════════════════════════════════════════════════════════════

    def _action_choose_folder(self):
        last = self._settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", last)
        if folder:
            self.le_folder.setText(folder)
            self._settings.setValue("last_folder", folder)
            self.lbl_folder_info.setText("Carpeta seleccionada. Hacé clic en 'Escanear carpeta'.")
            if not self.le_output.text():
                self.le_output.setText(str(Path(folder) / "patron_polar.npz"))

    def _on_template_changed(self, text: str):
        try:
            preview = template_preview(text, 45, 30)
            self.lbl_preview.setText(preview)
            self.lbl_preview.setStyleSheet("color:#7c8aaa; font-family:monospace; background:transparent;")
        except Exception as e:
            self.lbl_preview.setText(str(e))
            self.lbl_preview.setStyleSheet("color:#f87171; background:transparent;")

    def _on_modo_seleccion_changed(self, modo: str):
        """Alterna entre selectores de rango y grilla de checkboxes."""
        es_rango = (modo == "Rango (Mín/Máx)")
        
        self.rango_container.setVisible(es_rango)
        self.band_filter.setVisible(not es_rango)        

    def _on_tipo_banda_changed(self, tipo: str):
        """Actualiza las frecuencias disponibles según la resolución elegida."""
        if tipo == "Por Octava":
            # Array de bandas de octava estándar
            bandas = np.array(ISO_BANDS_OCTAVE)
        else:
            # Array de tercios (tu variable global)
            bandas = np.array(ISO_BANDS_HZ)
            
        # 1. Actualizamos los checkboxes
        self.band_filter.set_bands(bandas)
        
        # 2. Actualizamos los desplegables de rango guardando el array actual
        self._bandas_actuales = bandas # Guardamos el array para usarlo al procesar
        self._actualizar_combos_rango(bandas)

    def _actualizar_combos_rango(self, bandas):
        """Llena los comboboxes de Mín y Máx con labels amigables."""
        # Evitamos que se disparen eventos de cambio mientras llenamos
        self.cb_banda_min.blockSignals(True)
        self.cb_banda_max.blockSignals(True)
        
        self.cb_banda_min.clear()
        self.cb_banda_max.clear()
        
        # Asumiendo que tenés importado 'freq_label' desde tu core.data_store
        labels = [f"{freq_label(b)} Hz" for b in bandas]
        
        self.cb_banda_min.addItems(labels)
        self.cb_banda_max.addItems(labels)
        
        # Por defecto: el mínimo en el primer elemento, el máximo en el último
        if len(labels) > 0:
            self.cb_banda_min.setCurrentIndex(0)
            self.cb_banda_max.setCurrentIndex(len(labels) - 1)
            
        self.cb_banda_min.blockSignals(False)
        self.cb_banda_max.blockSignals(False)

    def _action_scan(self):
        folder   = self.le_folder.text().strip()
        template = self.le_template.text().strip()

        if not folder or not template:
            self._set_match_status("error", "Ingresá carpeta y template.")
            return

        files, unmatched, err = scan_folder(folder, template)

        if err:
            self._set_match_status("error", f"Error: {err}")
            self._files = []
            self.btn_process.setEnabled(False)
            return

        self._files = files
        if not files:
            self._set_match_status("warn", f"No se encontraron archivos. ({len(unmatched)} no coinciden)")
            self.btn_process.setEnabled(False)
            return

        grid = get_grid_info(files)
        complete_str = "✓ Completa" if grid.get('complete') else "⚠ Incompleta"
        h_step = f"{grid['h_step']:.1f}°" if grid.get('h_step') else "variable"

        info = (
            f"✓ {len(files)} archivos\n"
            f"{grid['n_az']}×{grid['n_el']} {complete_str}\n"
            f"H: {h_step} paso"
        )
        self._set_match_status("ok", info)
        self.btn_process.setEnabled(True)
        self._log(f"✓ Escaneado: {len(files)} archivos")

    def _action_choose_output(self):
        last = self._settings.value("last_output", "")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar en", last, "*.npz")
        if path:
            if not path.endswith(".npz"):
                path += ".npz"
            self.le_output.setText(path)
            self._settings.setValue("last_output", path)

    def _action_process(self):
        if not self._files or not self.le_output.text().strip():
            self._set_match_status("error", "Configura todo antes de procesar.")
            return

        try:
            from audio_processor import process_audio
        except ImportError as e:
            self._log(f"✖ No se pudo importar audio_processor: {e}")
            return

        # Leemos la configuración actual de la interfaz
        modo = self.cb_modo_seleccion.currentText()
        resolucion = self.cb_tipo_banda.currentText() # "Por Octava" o "Por Tercio de Octava"

        if modo == "Personalizada":
            selected_bands = self.band_filter.get_selected_bands()
            if not selected_bands:
                QMessageBox.warning(self, "Advertencia", "Seleccioná al menos una banda para procesar.")
                return
        else:
            idx_min = self.cb_banda_min.currentIndex()
            idx_max = self.cb_banda_max.currentIndex()
            
            # Validación sencilla por si el usuario pone el min más alto que el max
            if idx_min > idx_max:
                QMessageBox.warning(self, "Advertencia", "La banda mínima no puede ser mayor que la máxima.")
                return
                
            # Extraemos del array guardado usando un slice de numpy/python
            # Le sumamos 1 a idx_max porque el slice final no es inclusivo
            selected_bands = self._bandas_actuales[idx_min:idx_max + 1].tolist()     

        self.btn_process.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.progress_bar.setVisible(True)
        self.lbl_progress.setVisible(True)
        self.progress_bar.setMaximum(len(self._files))

        self._worker = ProcessWorker(
            files=self._files,
            process_fn=process_audio,
            output_path=self.le_output.text().strip(),
            band_width=resolucion,
            selected_bands=selected_bands,
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.log_msg.connect(self._log)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _action_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)
            self._log("✖ Procesamiento cancelado.")

    def _on_worker_progress(self, current: int, total: int, filename: str):
        self.progress_bar.setValue(current)
        self.lbl_progress.setText(f"[{current}/{total}] {filename}")

    def _on_worker_finished(self, result: dict):
        self._reset_process_ui()
        self._load_polar_into_view(result)
        self._log(f"✓ Procesamiento finalizado")
        self.stacked.setCurrentIndex(1)

    def _on_worker_error(self, msg: str):
        self._reset_process_ui()
        self._log(f"✖ Error: {msg}")

    def _reset_process_ui(self):
        self.btn_process.setEnabled(bool(self._files))
        self.btn_cancel.setVisible(False)
        self.progress_bar.setVisible(False)
        self.lbl_progress.setVisible(False)
        self._worker = None

    def _action_open_npz(self):
        last = self._settings.value("last_npz", "")
        path, _ = QFileDialog.getOpenFileName(self, "Abrir NPZ", last, "*.npz")
        if not path:
            return
        self._settings.setValue("last_npz", path)
        try:
            data = load_polar(path)
            self._load_polar_into_view(data)
            self._log(f"✓ Cargado: {Path(path).name}")
            self.stacked.setCurrentIndex(1)
        except Exception as e:
            self._log(f"✖ Error: {e}")

    def _load_polar_into_view(self, data: dict):
        self._polar = data
        bands = data['bands']
        self.band_selector.set_bands(bands)

        self.balloon_view.set_data(
            levels=data['levels'],
            azimuths=data['azimuths'],
            elevations=data['elevations'],
            bands=bands,
            band_index=self.band_selector.current_index,
            symmetry_type='none',
        )

        # Cargar también en el plot 2D con simetría (por defecto: ninguna)
        self.cb_symmetry.setCurrentText("Ninguna")
        self.polar_2d.set_data(
            levels=data['levels'],
            azimuths=data['azimuths'],
            elevations=data['elevations'],
            band_index=self.band_selector.current_index,
            el_index=0,  # Mostrar la primera elevación (típicamente 0°)
            symmetry_type='none'
        )

        # Update header
        n_bands = len(bands)
        self.lbl_header_filename.setText(f"Dataset: {n_bands} bandas")
        self.lbl_header_shape.setText(f"Shape: {data['levels'].shape}")

        # Update stats
        # self._update_stats_panel(data)

    def _update_stats_panel(self, data: dict):
        levels = data['levels']
        bands = data['bands']
        az = data['azimuths']
        el = data['elevations']

        # Dataset stats
        self.lbl_n_files.setText(f"Archivos: {len(self._files)}")
        self.lbl_grid.setText(f"Grilla: {len(az)} × {len(el)}")
        self.lbl_az_range.setText(f"Az: {az.min():.0f}° → {az.max():.0f}°")
        self.lbl_el_range.setText(f"El: {el.min():.0f}° → {el.max():.0f}°")

        # Band stats
        while self.bands_stats_lay.count() > 1:
            self.bands_stats_lay.takeAt(0).widget().deleteLater()

        for i, band_hz in enumerate(bands):
            band_data = levels[:, :, i]
            min_val = np.nanmin(band_data)
            max_val = np.nanmax(band_data)
            avg_val = np.nanmean(band_data)

            label_text = f"{freq_label(band_hz)}: {min_val:.1f}  {avg_val:.1f}  {max_val:.1f}"
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:#7c8aaa; font-size:8pt; background:transparent;")
            self.bands_stats_lay.insertWidget(i, lbl)

    @pyqtSlot(int, float)
    def _on_band_changed(self, index: int, hz: float):
        self.balloon_view.set_band(index)
        # Actualizar también el plot 2D con simetría
        if self._polar:
            symmetry_map = {"Ninguna": "none", "Azimut": "azimuth", 
                           "Elevación": "elevation", "Ambas": "both"}
            sym_type = symmetry_map.get(self.cb_symmetry.currentText(), "none")
            self.polar_2d.set_data(
                levels=self._polar['levels'],
                azimuths=self._polar['azimuths'],
                elevations=self._polar['elevations'],
                band_index=index,
                el_index=0,
                symmetry_type=sym_type
            )
        self.statusBar().showMessage(f"Banda: {freq_label(hz)} Hz")

    def _on_symmetry_changed(self, text: str):
        """Actualiza los plots cuando cambia el tipo de simetría."""
        if self._polar:
            symmetry_map = {"Ninguna": "none", "Azimut": "azimuth", 
                           "Elevación": "elevation", "Ambas": "both"}
            sym_type = symmetry_map.get(text, "none")
            band_idx = self.band_selector.current_index
            
            # Actualizar ambos plots con la nueva simetría
            self.balloon_view.set_data(
                levels=self._polar['levels'],
                azimuths=self._polar['azimuths'],
                elevations=self._polar['elevations'],
                bands=self._polar['bands'],
                band_index=band_idx,
                symmetry_type=sym_type,
            )
            self.polar_2d.set_data(
                levels=self._polar['levels'],
                azimuths=self._polar['azimuths'],
                elevations=self._polar['elevations'],
                band_index=band_idx,
                el_index=0,
                symmetry_type=sym_type
            )

    def _on_fix_range_changed(self, state: int):
        fixed = state == 2
        self.spin_min.setEnabled(fixed)
        self.spin_max.setEnabled(fixed)
        if fixed:
            self.balloon_view.set_db_range(self.spin_min.value(), self.spin_max.value())
            self.polar_2d.set_db_range(self.spin_min.value(), self.spin_max.value())
        else:
            self.balloon_view.set_db_range(None, None)
            self.polar_2d.set_db_range(None, None)

    def _on_spin_range_changed(self):
        """Actualiza el gráfico si el usuario cambia los números y la casilla está tildada."""
        # Solo actualizamos si el checkbox está activado
        if self.chk_fix_range.isChecked():
            self.balloon_view.set_db_range(self.spin_min.value(), self.spin_max.value())
            self.polar_2d.set_db_range(self.spin_min.value(), self.spin_max.value())

    def _toggle_stats_panel(self, checked: bool):
        """Show/hide stats panel and adjust plot sizes."""
        self.right_panel.setVisible(bool(checked))
        # Adjust splitter to give plots more space when stats hidden
        try:
            main_widget = self.stacked.widget(1)
            splitter = main_widget.findChild(QSplitter)
            if splitter:
                if checked:
                    splitter.setSizes([1100, 280])
                else:
                    splitter.setSizes([1400, 0])
        except Exception:
            pass

    def _set_plot_mode(self, mode: str, checked: bool):
        """Toggle between 3D-only, 2D-only, or both plots."""
        if mode == "3d":
            self.btn_3d.setChecked(bool(checked))
            self.balloon_view.setVisible(bool(checked))
        elif mode == "2d":
            self.btn_2d.setChecked(bool(checked))
            self.polar_2d.setVisible(bool(checked))

    @pyqtSlot(str)
    def _on_point_hovered(self, json_str: str):
        try:
            d = json.loads(json_str)
            text = d.get('text', '').replace('<br>', '  ')
            self.lbl_hover.setText(text)
        except:
            pass

    def _action_export_csv(self):
        if not self._polar:
            QMessageBox.warning(self, "Advertencia", "No hay datos para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Exportar CSV", "", "*.csv")
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"

        try:
            import pandas as pd
            levels = self._polar['levels']
            bands = self._polar['bands']
            az = self._polar['azimuths']
            el = self._polar['elevations']

            data = []
            for i, band in enumerate(bands):
                for j, a in enumerate(az):
                    for k, e in enumerate(el):
                        data.append({
                            'banda_hz': band,
                            'azimut': a,
                            'elevacion': e,
                            'nivel_db': levels[j, k, i],
                        })

            df = pd.DataFrame(data)
            df.to_csv(path, index=False)
            self._log(f"✓ Exportado: {Path(path).name}")
        except Exception as e:
            self._log(f"✖ Error exportando CSV: {e}")

    def _action_export_image(self):
        QMessageBox.info(self, "Info", "Captura la pantalla con Print Screen o usa la función del navegador.")

    def _action_export_npz(self):
        if not self._polar:
            QMessageBox.warning(self, "Advertencia", "No hay datos para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Guardar NPZ", "", "*.npz")
        if not path:
            return
        if not path.endswith(".npz"):
            path += ".npz"

        try:
            from core.data_store import save_polar
            save_polar(
                path,
                levels=self._polar['levels'],
                azimuths=self._polar['azimuths'],
                elevations=self._polar['elevations'],
                bands=self._polar['bands'],
            )
            self._log(f"✓ Exportado: {Path(path).name}")
        except Exception as e:
            self._log(f"✖ Error: {e}")

    def _set_match_status(self, kind: str, text: str):
        colors = {"ok": "#51cf66", "warn": "#ffa94d", "error": "#f87171"}
        self.lbl_match_status.setText(text)
        self.lbl_match_status.setStyleSheet(f"color:{colors.get(kind, '#c8ccd8')}; font-size:8.5pt; background:transparent;")

    def _log(self, msg: str):
        self.log_edit.append(msg)
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _restore_settings(self):
        if folder := self._settings.value("last_folder", ""):
            if Path(folder).is_dir():
                self.le_folder.setText(folder)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        self._settings.setValue("last_folder", self.le_folder.text())
        self._settings.setValue("last_output", self.le_output.text())
        super().closeEvent(event)
