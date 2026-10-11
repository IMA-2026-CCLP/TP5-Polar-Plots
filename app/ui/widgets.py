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


# ── Fila que se envuelve (como flex-wrap): todo en una línea si entra, si no baja a la siguiente ──────────

from PyQt6.QtCore import QRect, QSize, QPoint, Qt as _Qt
from PyQt6.QtWidgets import QLayout as _QLayout, QSizePolicy as _QSizePolicy


class FlowLayout(_QLayout):
    """Acomoda sus items de izquierda a derecha y, cuando no entran en el ancho disponible, sigue en la fila
    de abajo. Soporta altura según el ancho (heightForWidth), así que el contenedor crece solo al envolver."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return _Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def preferred_width(self):
        """Ancho que hace falta para que todo quede en una sola fila."""
        m = self.contentsMargins()
        return (sum(it.sizeHint().width() for it in self._items) + self._spacing * max(0, len(self._items) - 1)
                + m.left() + m.right())

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, apply):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and line_h > 0:      # no entra: fila siguiente
                x = r.x()
                y += line_h + self._spacing
                line_h = 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()
