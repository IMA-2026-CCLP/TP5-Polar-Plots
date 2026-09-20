"""ui/widgets.py — Widgets chicos compartidos entre tabs."""
from PyQt6.QtWidgets import QLineEdit


class NumEdit(QLineEdit):
    """Campo de texto simple para valores numéricos — reemplaza a
    QDoubleSpinBox/QSpinBox en toda la app (sin flechitas de
    incremento/decremento, sólo texto editable). Replica el API mínimo
    usado (setRange/setSingleStep/setDecimals/setValue/value) para no
    tener que tocar el resto del código que arma los campos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lo = None
        self._hi = None
        self._decimals = 2
        self.setFixedWidth(70)

    def setRange(self, lo, hi):
        self._lo, self._hi = lo, hi

    def setSingleStep(self, step):
        pass   # sin flechitas, no aplica

    def setDecimals(self, n):
        self._decimals = n

    def setValue(self, v):
        self.setText(str(int(round(v))) if self._decimals == 0 else f"{v:g}")

    def value(self) -> float:
        try:
            v = float(self.text().strip().replace(',', '.'))
        except ValueError:
            v = 0.0
        if self._lo is not None:
            v = max(self._lo, v)
        if self._hi is not None:
            v = min(self._hi, v)
        return v
