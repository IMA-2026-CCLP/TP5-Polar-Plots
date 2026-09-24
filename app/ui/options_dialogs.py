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


class SmoothingOptionsDialog(QDialog):
    """Suavizado — una sola configuración para Polar 2D, Superficie 3D y Esfera (Herramientas ▸
    Suavizado…). Antes cada gráfico tenía su propio panel de Suavizado en Propiedades, duplicado
    y a veces desalineado entre los tres; ahora es un único lugar que los tres respetan igual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Suavizado")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)

        intro = QLabel("Se aplica por igual a Polar 2D, Superficie 3D y Esfera.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self._method = QComboBox()
        self._method.addItems(['gaussian', 'savgol', 'moving_average', 'none'])
        self._method.setToolTip(
            "Sólo importa si la 'Intensidad' de abajo es mayor a 0.\n"
            "gaussian: recomendado para empezar, no genera ondulaciones falsas.\n"
            "savgol (Savitzky-Golay): usalo si el gaussiano 'redondea' demasiado\n"
            "  un lóbulo o nulo que sabés que es real.\n"
            "moving_average: el más simple, puede generar ondulaciones que no\n"
            "  existen en la medición real.\n"
            "none: sin suavizar, ignora la intensidad.")
        form.addRow("Tipo de suavizado:", self._method)

        self._window = NumEdit()
        self._window.setDecimals(0)
        self._window.setRange(0, 15)
        self._window.setToolTip(
            "Cantidad de puntos vecinos que se promedian entre sí.\n"
            "0 = sin suavizar. 3 a 5 = leve. 7 a 9 = fuerte (cuidado, puede\n"
            "borrar lóbulos/nulos reales). No recomendado pasar de 10.")
        form.addRow("Intensidad (0 = sin suavizar):", self._window)

        self._interp_deg = NumEdit()
        self._interp_deg.setRange(0.1, 10.0)
        self._interp_deg.setToolTip(
            "Qué tan fina se dibuja la curva/superficie entre los puntos medidos.\n"
            "No cambia los datos. Recomendado: 1 a 2. Bajalo para exportar con más\n"
            "nitidez; subilo si sentís que el gráfico va lento.")
        form.addRow("Paso de interpolación (°):", self._interp_deg)

        self._interp_kind = QComboBox()
        self._interp_kind.addItems(['cubic', 'quadratic', 'linear', 'none'])
        self._interp_kind.setToolTip(
            "Sólo Polar 2D (su curva es 1D). cubic: recomendado. linear: se ve\n"
            "'picudo'. none: sólo los puntos medidos, sin curva.")
        form.addRow("Tipo de interpolación (Polar 2D):", self._interp_kind)

        self._spline_factor = NumEdit()
        self._spline_factor.setRange(0.0, 500.0)
        self._spline_factor.setToolTip(
            "Sólo Superficie 3D/Esfera (su malla es una spline 2D). 0 = pasa exacto\n"
            "por los datos medidos (recomendado). Valores altos (200+) empiezan a\n"
            "deformar la forma real — subilo de a poco si hace falta.")
        form.addRow("Suavizado de la malla 3D:", self._spline_factor)
        lay.addLayout(form)

        row = QDialogButtonBox()
        b_reset = row.addButton("Restaurar por defecto", QDialogButtonBox.ButtonRole.ResetRole)
        b_reset.setAutoDefault(False)
        b_reset.clicked.connect(self._reset)
        row.addButton("Guardar", QDialogButtonBox.ButtonRole.AcceptRole)
        row.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        row.accepted.connect(self._accept)
        row.rejected.connect(self.reject)
        lay.addWidget(row)

        self._load(eu.get_smoothing_settings())

    def _load(self, v: dict):
        self._method.setCurrentText(v["smoothing_method"])
        self._window.setValue(v["smoothing_window"])
        self._interp_deg.setValue(v["interp_deg"])
        self._interp_kind.setCurrentText(v["interp_kind"])
        self._spline_factor.setValue(v["spline_factor"])

    def _reset(self):
        self._load(eu.DEFAULT_SMOOTHING)

    def values(self) -> dict:
        return dict(
            smoothing_method=self._method.currentText(),
            smoothing_window=self._window.value(),
            interp_deg=self._interp_deg.value(),
            interp_kind=self._interp_kind.currentText(),
            spline_factor=self._spline_factor.value(),
        )

    def _accept(self):
        eu.set_smoothing_settings(self.values())
        self.accept()
