"""
ui/band_selector.py — Selector horizontal de bandas de tercio de octava.

Rediseño: los chips y el valor activo se estilan desde el QSS global
(objectName 'band_chip' / 'band_current'), por lo que reaccionan al
cambio de tema sin código extra. Reemplazo directo del original.
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.data_store import freq_label


class BandButton(QPushButton):
    def __init__(self, hz: float, index: int, parent=None):
        super().__init__(parent)
        self.hz    = hz
        self.index = index
        self.setObjectName("band_chip")          # estilo desde el QSS global
        self.setText(freq_label(hz))
        self.setFixedWidth(46)
        self.setFixedHeight(38)
        self.setCheckable(True)
        self.setToolTip(f"{hz} Hz")

    def set_active(self, active: bool):
        self.setChecked(active)                  # :checked lo pinta el QSS


class BandSelectorWidget(QWidget):
    """
    Selector de banda de tercio de octava.
    Emite band_changed(index, hz) al cambiar.
    """
    band_changed = pyqtSignal(int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bands: np.ndarray = np.array([])
        self.current_index = 0
        self._buttons: list[BandButton] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("BANDA DE TERCIO DE OCTAVA")
        lbl.setObjectName("label_badge")
        header.addWidget(lbl)
        header.addStretch()
        self.lbl_current = QLabel("—")
        self.lbl_current.setObjectName("band_current")   # estilo desde el QSS
        header.addWidget(self.lbl_current)
        root.addLayout(header)

        nav = QHBoxLayout()
        btn_prev = QPushButton("◀")
        btn_prev.setObjectName("btn_icon")
        btn_prev.clicked.connect(self.prev_band)
        nav.addWidget(btn_prev)

        self._btn_container = QWidget()
        self._btn_layout    = QHBoxLayout(self._btn_container)
        self._btn_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_layout.setSpacing(4)
        self._btn_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._btn_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll
        nav.addWidget(scroll)

        btn_next = QPushButton("▶")
        btn_next.setObjectName("btn_icon")
        btn_next.clicked.connect(self.next_band)
        nav.addWidget(btn_next)
        root.addLayout(nav)

    # ── API pública ───────────────────────────────────────────────────────

    def set_bands(self, bands: np.ndarray):
        self.bands = bands.copy()
        self.current_index = 0
        for btn in self._buttons:
            btn.deleteLater()
        self._buttons.clear()
        while self._btn_layout.count() > 1:
            item = self._btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
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

    def _on_button(self, index: int):
        self.set_index(index)
        self.band_changed.emit(self.current_index, self.current_band_hz())

    def _refresh_buttons(self, active_idx: int):
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == active_idx)

    def _scroll_to_button(self, index: int):
        if 0 <= index < len(self._buttons):
            self._scroll.ensureWidgetVisible(self._buttons[index])
