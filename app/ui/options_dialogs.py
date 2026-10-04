"""ui/options_dialogs.py — Diálogos del menú Opciones ▸ Gráficos que no son de un gráfico en particular."""
from PyQt6.QtWidgets import (
    QGroupBox,
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
    """Suavizado (Herramientas ▸ Suavizado…): configuración independiente para cada gráfico —
    Superficie 3D, Esfera y Polar 2D — cada uno con su tipo de suavizado e intensidad."""

    _METHOD_TIP = (
        "Sólo importa si la 'Intensidad' es mayor a 0.\n"
        "gaussian: recomendado para empezar, no genera ondulaciones falsas.\n"
        "savgol (Savitzky-Golay): usalo si el gaussiano 'redondea' demasiado\n"
        "  un lóbulo o nulo que sabés que es real.\n"
        "moving_average: el más simple, puede generar ondulaciones que no\n"
        "  existen en la medición real.\n"
        "none: sin suavizar, ignora la intensidad.")
    _WINDOW_TIP = (
        "Con gaussian es la σ del filtro: 1 = leve, 2 = medio, 3 = fuerte.\n"
        "0 = sin suavizar. Con savgol/moving_average es el tamaño de la ventana.")
    _TITLES = {"3d": "Superficie 3D", "sphere": "Esfera", "polar2d": "Polar 2D"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Suavizado")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        self._fields: dict[str, dict] = {}

        for mode in eu.SMOOTHING_MODES:
            box = QGroupBox(self._TITLES[mode])
            form = QFormLayout(box)
            f = {}
            f["smoothing_method"] = QComboBox()
            f["smoothing_method"].addItems(['gaussian', 'savgol', 'moving_average', 'none'])
            f["smoothing_method"].setToolTip(self._METHOD_TIP)
            form.addRow("Tipo de suavizado:", f["smoothing_method"])

            f["smoothing_window"] = NumEdit()
            f["smoothing_window"].setDecimals(0)
            f["smoothing_window"].setRange(0, 15)
            f["smoothing_window"].setToolTip(self._WINDOW_TIP)
            form.addRow("Intensidad (0 = sin suavizar):", f["smoothing_window"])

            f["interp_deg"] = NumEdit()
            f["interp_deg"].setRange(0.1, 10.0)
            f["interp_deg"].setToolTip(
                "Qué tan fina se dibuja la curva/superficie entre los puntos medidos.\n"
                "No cambia los datos. Recomendado: 1 a 2.")
            form.addRow("Paso de interpolación (°):", f["interp_deg"])

            if mode == "polar2d":
                f["interp_kind"] = QComboBox()
                f["interp_kind"].addItems(['cubic', 'quadratic', 'linear', 'none'])
                f["interp_kind"].setToolTip(
                    "Tipo de spline 1D. cubic: recomendado. linear: se ve 'picudo'. none: sólo\n"
                    "los puntos medidos, sin curva.")
                form.addRow("Tipo de interpolación:", f["interp_kind"])
            else:
                f["spline_factor"] = NumEdit()
                f["spline_factor"].setRange(0.0, 500.0)
                f["spline_factor"].setToolTip(
                    "0 = pasa exacto por los datos medidos (recomendado). Valores altos (200+)\n"
                    "empiezan a deformar la forma real — subilo de a poco si hace falta.")
                form.addRow("Suavizado de la malla 3D:", f["spline_factor"])

            self._fields[mode] = f
            lay.addWidget(box)

        row = QDialogButtonBox()
        b_reset = row.addButton("Restaurar por defecto", QDialogButtonBox.ButtonRole.ResetRole)
        b_reset.setAutoDefault(False)
        b_reset.clicked.connect(self._reset)
        row.addButton("Guardar", QDialogButtonBox.ButtonRole.AcceptRole)
        row.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        row.accepted.connect(self._accept)
        row.rejected.connect(self.reject)
        lay.addWidget(row)

        self._load({m: eu.get_smoothing_settings(m) for m in eu.SMOOTHING_MODES})

    def _load(self, by_mode: dict):
        for mode, v in by_mode.items():
            for k, w in self._fields[mode].items():
                if isinstance(w, QComboBox):
                    w.setCurrentText(str(v[k]))
                else:
                    w.setValue(v[k])

    def _reset(self):
        self._load(eu.DEFAULT_SMOOTHING_BY_MODE)

    def values(self) -> dict:
        """{modo: {smoothing_method, smoothing_window, interp_deg, spline_factor | interp_kind}}"""
        return {mode: {k: (w.currentText() if isinstance(w, QComboBox)
                           else int(w.value()) if k == 'smoothing_window' else w.value())
                       for k, w in f.items()}
                for mode, f in self._fields.items()}

    def _accept(self):
        for mode, v in self.values().items():
            eu.set_smoothing_settings(mode, v)
        self.accept()
