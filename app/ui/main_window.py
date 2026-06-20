"""
ui/main_window.py — Ventana principal con 4 tabs.
"""
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QDockWidget, QTextEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QTextCursor

from ui.styles                import QSS
from ui.tab_carga             import TabCarga
from ui.tab_preprocesamiento  import TabPreprocesamiento
from ui.tab_calibracion       import TabCalibracion
from ui.tab_notas             import TabNotas
from ui.tab_directividad      import TabDirectividad


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Polar Pattern Analyzer")
        self.setMinimumSize(1200, 750)
        self.resize(1440, 860)
        self.setStyleSheet(QSS)

        self._ma       = None
        self._settings = QSettings("AcousticTools", "PolarAnalyzerV2")

        self._build_ui()
        self._restore_geometry()

    # ── Construcción ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        top = self._make_top_bar()

        # Tabs
        self.tabs = QTabWidget()
        self.tab_carga       = TabCarga()
        self.tab_prepro      = TabPreprocesamiento()
        self.tab_calibracion = TabCalibracion()
        self.tab_notas       = TabNotas()
        self.tab_dir         = TabDirectividad()

        self.tabs.addTab(self.tab_carga,       "Carga")
        self.tabs.addTab(self.tab_prepro,      "Preprocesamiento")
        self.tabs.addTab(self.tab_calibracion, "Calibración")
        self.tabs.addTab(self.tab_notas,       "Detección de notas")
        self.tabs.addTab(self.tab_dir,         "Directividad")

        # Señales de propagación de MicArray entre tabs
        self.tab_carga.ma_ready.connect(self._on_ma_ready)
        self.tab_carga.log.connect(self._append_log)

        self.tab_prepro.ma_updated.connect(self._on_ma_ready)
        self.tab_prepro.log.connect(self._append_log)

        self.tab_calibracion.ma_updated.connect(self._on_ma_ready)
        self.tab_calibracion.log.connect(self._append_log)

        self.tab_notas.ma_updated.connect(self._on_ma_ready)
        self.tab_notas.log.connect(self._append_log)

        self.tab_dir.log.connect(self._append_log)

        # Layout central
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(top)
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # Log dock
        self._setup_log_dock()

        # Status bar
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

    def _make_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(56)
        bar.setStyleSheet("""
            QWidget { background: #12141e; border-bottom: 1px solid #2a2d3e; }
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        dot = QLabel("⬡")
        dot.setStyleSheet("color:#5865a0; font-size:18pt; background:transparent; border:none;")
        lay.addWidget(dot)

        lbl = QLabel("Polar Pattern Analyzer")
        lbl.setObjectName("label_title")
        lbl.setStyleSheet(
            "font-size:14pt; font-weight:700; color:#e8ecf4;"
            "background:transparent; border:none;"
        )
        lay.addWidget(lbl)
        lay.addStretch()

        self.lbl_tensor_info = QLabel("")
        self.lbl_tensor_info.setObjectName("label_subtitle")
        self.lbl_tensor_info.setStyleSheet(
            "color:#5a6080; font-size:9pt; background:transparent; border:none;"
        )
        lay.addWidget(self.lbl_tensor_info)

        return bar

    def _setup_log_dock(self):
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))

        dock = QDockWidget("Log", self)
        dock.setWidget(self._log)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.setMaximumHeight(200)

    # ── Propagación de MicArray ───────────────────────────────────────────

    def _on_ma_ready(self, ma):
        self._ma = ma
        shape    = ma.tensor.shape
        self.lbl_tensor_info.setText(
            f"Tensor {shape}  ·  sr {ma.sr} Hz  ·  "
            f"Cal: {'OK' if ma.calibration is not None else '—'}  ·  "
            f"SPL: {'OK' if ma._is_spl else '—'}  ·  "
            f"Notas: {len(ma.notes) if ma.notes else 0}"
        )
        # Propagar a todos los tabs
        self.tab_prepro.set_ma(ma)
        self.tab_calibracion.set_ma(ma)
        self.tab_notas.set_ma(ma)
        self.tab_dir.set_ma(ma)
        self.statusBar().showMessage(f"Tensor cargado — {shape}")

    # ── Log ───────────────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text + "\n")
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    # ── Persistencia ──────────────────────────────────────────────────────

    def _restore_geometry(self):
        geom = self._settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)

    def closeEvent(self, event):
        self._settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)
