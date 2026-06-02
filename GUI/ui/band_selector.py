"""
ui/band_selector.py — Selector horizontal de bandas de tercio de octava
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QColor, QPen

from core.data_store import freq_label


class BandButton(QPushButton):
    """Botón individual de banda con etiqueta de frecuencia."""

    def __init__(self, hz: float, index: int, parent=None):
        super().__init__(parent)
        self.hz = hz
        self.index = index
        self._active = False

        label = freq_label(hz)
        self.setText(label)
        self.setFixedWidth(46)
        self.setFixedHeight(38)
        self.setCheckable(True)
        self.setToolTip(f"{hz} Hz")
        self._update_style()

    def set_active(self, active: bool):
        self._active = active
        self.setChecked(active)
        self._update_style()

    def _update_style(self):
        if self._active:
            self.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                        stop:0 #5865a0, stop:1 #4253a0);
                    color: #ffffff;
                    border: none;
                    border-radius: 7px;
                    font-size: 8pt;
                    font-weight: 700;
                    padding: 0;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: #1f2235;
                    color: #7c8aaa;
                    border: 1px solid #2a2d3e;
                    border-radius: 7px;
                    font-size: 8pt;
                    font-weight: 500;
                    padding: 0;
                }
                QPushButton:hover {
                    background: #2a2d3e;
                    color: #c8ccd8;
                    border-color: #3b3f58;
                }
            """)


class BandSelectorWidget(QWidget):
    """
    Widget completo de selección de banda: fila de botones + slider.
    Emite band_changed(index, hz) cuando el usuario cambia de banda.
    """
    band_changed = pyqtSignal(int, float)  # (band_index, hz)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bands: np.ndarray = np.array([])
        self.current_index = 0
        self._buttons: list[BandButton] = []
        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Cabecera
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("BANDA DE TERCIO DE OCTAVA")
        lbl.setObjectName("label_badge")
        header.addWidget(lbl)
        header.addStretch()

        self.lbl_current = QLabel("—")
        self.lbl_current.setStyleSheet("""
            color: #c8ccd8;
            font-size: 12pt;
            font-weight: 700;
        """)
        header.addWidget(self.lbl_current)
        root.addLayout(header)

        nav = QHBoxLayout()
        # nav.setSpacing(8)        

        btn_prev = QPushButton("◀")
        btn_prev.setObjectName("btn_icon")
        # btn_prev.setFixedWidth(28)
        btn_prev.clicked.connect(self.prev_band)
        nav.addWidget(btn_prev)

        # Contenedor de botones con scroll
        from PyQt6.QtWidgets import QScrollArea, QFrame
        self._btn_container = QWidget()
        self._btn_layout = QHBoxLayout(self._btn_container)
        self._btn_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_layout.setSpacing(4)
        self._btn_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._btn_container)
        scroll.setWidgetResizable(True)
        # scroll.setFixedHeight(54)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll
        nav.addWidget(scroll)

        btn_next = QPushButton("▶")
        btn_next.setObjectName("btn_icon")
        # btn_next.setFixedWidth(28)
        btn_next.clicked.connect(self.next_band)

        # nav.addStretch()
        nav.addWidget(btn_next)
        root.addLayout(nav)

        # self.setFixedHeight(110)

    # ── API pública ───────────────────────────────────────────────────────

    def set_bands(self, bands: np.ndarray):
        """Recibe el array de frecuencias y reconstruye los botones."""
        self.bands = bands.copy()
        self.current_index = 0

        # Limpiar botones anteriores
        for btn in self._buttons:
            btn.deleteLater()
        self._buttons.clear()
        # Quitar widgets del layout (excepto stretch final)
        while self._btn_layout.count() > 1:
            item = self._btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Crear nuevos botones
        for i, hz in enumerate(bands):
            btn = BandButton(float(hz), i)
            btn.clicked.connect(lambda checked, idx=i: self._on_button(idx))
            self._btn_layout.insertWidget(i, btn)
            self._buttons.append(btn)

        self.set_index(0)

    def set_index(self, index: int):
        if not len(self.bands):
            return
        index = max(0, min(index, len(self.bands) - 1))
        if index == self.current_index and self._buttons:
            self._refresh_buttons(index)
            return
        self.current_index = index
        self._refresh_buttons(index)
        hz = float(self.bands[index])
        self.lbl_current.setText(f"{freq_label(hz)} Hz")
        self._scroll_to_button(index)

    def current_band_hz(self) -> float:
        if not len(self.bands):
            return 0.0
        return float(self.bands[self.current_index])

    def prev_band(self):
        self.set_index(self.current_index - 1)
        self.band_changed.emit(self.current_index, self.current_band_hz())

    def next_band(self):
        self.set_index(self.current_index + 1)
        self.band_changed.emit(self.current_index, self.current_band_hz())

    # ── Slots internos ────────────────────────────────────────────────────

    def _on_button(self, index: int):
        self.set_index(index)
        self.band_changed.emit(self.current_index, self.current_band_hz())

    def _refresh_buttons(self, active_idx: int):
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == active_idx)

    def _scroll_to_button(self, index: int):
        if 0 <= index < len(self._buttons):
            self._scroll.ensureWidgetVisible(self._buttons[index])
