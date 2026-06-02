"""
ui/band_filter.py — Selector para elegir qué bandas procesar
"""
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import pyqtSignal

from core.data_store import freq_label
from ui.flow_layout import FlowLayout

class BandFilterWidget(QWidget):
    """
    Widget para seleccionar qué bandas procesar.
    Por defecto, todas las bandas están seleccionadas.
    
    Emite: bands_selected(list[float]) cuando cambia la selección
    """
    bands_selected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bands: np.ndarray = np.array([])
        self._checkboxes: dict[float, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("BANDAS A PROCESAR")
        lbl.setObjectName("label_badge")
        header.addWidget(lbl)
        header.addStretch()

        btn_all = QPushButton("Todas")
        btn_all.setObjectName("btn_icon")
        # btn_all.setFixedWidth(50)
        btn_all.clicked.connect(self._select_all)
        header.addWidget(btn_all)

        btn_none = QPushButton("Ninguna")
        btn_none.setObjectName("btn_icon")
        # btn_none.setFixedWidth(60)
        btn_none.clicked.connect(self._select_none)
        header.addWidget(btn_none)

        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(180)

        container = QWidget()
        self._layout = FlowLayout(container, spacing=8)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        # self._layout.addStretch()

        scroll.setWidget(container)
        root.addWidget(scroll)
        self.setMaximumHeight(250)

    def set_bands(self, bands: np.ndarray):
        self.bands = bands.copy()
        self._checkboxes.clear()

        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for hz in bands:
            hz_float = float(hz)
            chk = QCheckBox(freq_label(hz_float))
            chk.setChecked(True)
            chk.stateChanged.connect(self._on_selection_changed)
            self._layout.addWidget(chk)
            self._checkboxes[hz_float] = chk

        self._emit_selection()

    def get_selected_bands(self) -> list[float]:
        return [hz for hz, chk in self._checkboxes.items() if chk.isChecked()]

    def _select_all(self):
        for chk in self._checkboxes.values():
            chk.blockSignals(True)
            chk.setChecked(True)
            chk.blockSignals(False)
        self._emit_selection()

    def _select_none(self):
        for chk in self._checkboxes.values():
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
        self._emit_selection()

    def _on_selection_changed(self):
        self._emit_selection()

    def _emit_selection(self):
        selected = self.get_selected_bands()
        self.bands_selected.emit(selected)
