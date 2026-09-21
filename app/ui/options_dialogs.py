"""ui/options_dialogs.py — Diálogos del menú Opciones ▸ Gráficos que no son de un gráfico en particular."""
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, QVBoxLayout,
)

from ui import export_utils as eu
from ui.widgets import NumEdit


class ImageOptionsDialog(QDialog):
    """Tamaño físico (cm), DPI y formato por defecto de las imágenes exportadas.

    El tamaño es fijo: cambiar el DPI sólo cambia los píxeles (la calidad), no el tamaño."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opciones — Imágenes")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)

        intro = QLabel(
            "Todas las imágenes exportadas salen con este tamaño físico. El DPI no cambia el tamaño: "
            "sólo la cantidad de píxeles (calidad, nitidez al ampliar).")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self._preset = QComboBox()
        for name, w, h in eu.SIZE_PRESETS:
            self._preset.addItem(name, (w, h))
        self._preset.addItem("Personalizado", None)
        self._preset.setToolTip("Tamaños habituales. El primero coincide con la proporción de cada gráfico en la grilla de 4.")
        form.addRow("Tamaño:", self._preset)

        self._w = NumEdit()
        self._w.setRange(3, 60)
        self._h = NumEdit()
        self._h.setRange(3, 60)
        form.addRow("Ancho (cm):", self._w)
        form.addRow("Alto (cm):", self._h)

        self._dpi = NumEdit()
        self._dpi.setRange(72, 1200)
        self._dpi.setDecimals(0)
        self._dpi.setToolTip("DPI que se propone al exportar. 300 es lo habitual para imprimir; 150 alcanza para pantalla.")
        form.addRow("DPI por defecto:", self._dpi)

        self._fmt = QComboBox()
        self._fmt.addItem("PNG (imagen)", "png")
        self._fmt.addItem("SVG (vectorial, sólo Polar 2D)", "svg")
        form.addRow("Formato por defecto:", self._fmt)
        lay.addLayout(form)

        self._preview = QLabel()
        self._preview.setObjectName("rb_status")
        lay.addWidget(self._preview)

        row = QDialogButtonBox()
        b_reset = row.addButton("Restaurar por defecto", QDialogButtonBox.ButtonRole.ResetRole)
        b_reset.setAutoDefault(False)
        b_reset.clicked.connect(self._reset)
        ok = row.addButton("Guardar", QDialogButtonBox.ButtonRole.AcceptRole)
        row.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        row.accepted.connect(self._accept)
        row.rejected.connect(self.reject)
        lay.addWidget(row)

        w, h = eu.get_export_size_cm()
        dpi, fmt = eu.get_export_defaults()
        self._load(w, h, dpi, fmt)
        self._preset.currentIndexChanged.connect(self._on_preset)
        for e in (self._w, self._h, self._dpi):
            e.textChanged.connect(self._update_preview)
        self._update_preview()

    def _load(self, w, h, dpi, fmt):
        self._w.setValue(w)
        self._h.setValue(h)
        self._dpi.setValue(dpi)
        self._fmt.setCurrentIndex(max(0, self._fmt.findData(fmt)))
        idx = next((i for i in range(self._preset.count() - 1)
                    if self._preset.itemData(i) == (w, h)), self._preset.count() - 1)
        self._preset.blockSignals(True)
        self._preset.setCurrentIndex(idx)
        self._preset.blockSignals(False)

    def _on_preset(self, _=None):
        wh = self._preset.currentData()
        if wh:
            self._w.setValue(wh[0])
            self._h.setValue(wh[1])

    def _update_preview(self, *_):
        w, h, dpi = self._w.value(), self._h.value(), self._dpi.value()
        self._preview.setText(f"{w:g} × {h:g} cm a {dpi:g} DPI = {round(w / 2.54 * dpi)} × {round(h / 2.54 * dpi)} px")
        match = next((i for i in range(self._preset.count() - 1) if self._preset.itemData(i) == (w, h)), None)
        self._preset.blockSignals(True)
        self._preset.setCurrentIndex(match if match is not None else self._preset.count() - 1)
        self._preset.blockSignals(False)

    def _reset(self):
        self._load(*eu.DEFAULT_SIZE_CM, eu.DEFAULT_DPI, "png")
        self._update_preview()

    def _accept(self):
        eu.set_export_size_cm(self._w.value(), self._h.value())
        eu.set_export_defaults(int(self._dpi.value()), self._fmt.currentData())
        self.accept()
