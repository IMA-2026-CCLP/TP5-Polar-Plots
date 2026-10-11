"""ui/matrix_dialog.py — Herramientas ▸ Matriz radial: mallado de mediciones (anillo = distancia al cénit,
sector = HOR). Cada celda muestra el nivel que le corresponde según la regla de simetría."""
import math
import os
import numpy as np
from PyQt6.QtCore import Qt, QSize, QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QShortcut, QKeySequence
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QDialogButtonBox,
                             QToolTip, QPushButton, QComboBox, QCheckBox, QFormLayout, QLineEdit, QMenu)
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtGui import QPainterPath

def _halo(p, path, color, width, glow_width):
    """Borde con halo suave: una línea ancha semitransparente por debajo y el borde firme encima."""
    # solo el contorno: el relleno (color en dB) lo pone quien llama con el pincel de la celda
    g = QColor(color); g.setAlphaF(0.5)
    p.setPen(QPen(g, glow_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)


THR_DB = 3.0   # diferencia máxima entre mediciones de una misma celda antes de marcarla


def _energy_mean(values):
    v = np.asarray(values, dtype=float)
    return float(10 * np.log10(np.mean(10 ** (v / 10.0))))


def _grid_step(azimuths):
    """Paso de la grilla en grados (10 para la medida; 5 si está interpolada)."""
    a = np.unique(np.round(np.asarray(azimuths, dtype=float), 6))
    return int(round(float(np.min(np.diff(a))))) if len(a) > 1 else 10


def radial_cells(levels, azimuths, thetas, overrides=None):
    """Devuelve {(d, hor): (valor, [(θ, giro, dB), ...])} con la regla de la matriz radial:
    d = |θ − 90°| (anillo), hor = giro/HOR de 10°. Delante (θ = 90 − d) mide HOR = giro;
    atrás (θ = 90 + d) mide HOR = giro + 180. En HOR 0° y 180° hay dos mediciones: se promedian
    en energía. El cénit (d = 0) promedia los giros de θ = 90°."""
    L = np.asarray(levels, dtype=float)
    az = [float(a) for a in azimuths]
    th = [float(t) for t in thetas]
    st = _grid_step(azimuths)
    def get(giro, t):
        ia = [i for i, a in enumerate(az) if abs(a - giro) < 0.5]
        it = [j for j, x in enumerate(th) if abs(x - t) < 0.5]
        return (L[ia[0], it[0]], giro, t) if ia and it and np.isfinite(L[ia[0], it[0]]) else None
    cells = {}
    cen = [get(g, 90.0) for g in az]
    cen = [c for c in cen if c]
    if cen:
        cells[(0, None)] = (_energy_mean([c[0] for c in cen]), [(c[2], c[1], c[0]) for c in cen])
    for d in range(st, 91, st):
        tf, tb = 90.0 - d, 90.0 + d
        for hor in range(0, 360, st):
            if overrides and (d, hor) in overrides:          # celda reemplazada por su espejo
                t_src, g_src = overrides[(d, hor)]
                m = get(g_src, t_src)
                if m:
                    cells[(d, hor)] = (m[0], [(m[2], m[1], m[0])])
                continue
            ms = []
            if hor <= 180 and get(hor, tf): ms.append(get(hor, tf))
            if hor >= 180 and get(hor - 180, tb): ms.append(get(hor - 180, tb))
            if hor == 0 and get(180, tb): ms.append(get(180, tb))          # costura: segunda medición
            if not ms:
                continue
            cells[(d, hor)] = (_energy_mean([m[0] for m in ms]), [(m[2], m[1], m[0]) for m in ms])
    return cells


class _Radial(QWidget):
    def __init__(self, levels, azimuths, thetas, source=None, on_click=None, parent=None):
        super().__init__(parent)
        self._az, self._th = azimuths, thetas
        self._step = _grid_step(azimuths)
        self._cells = radial_cells(levels, azimuths, thetas)
        self._source = source
        self._on_click = on_click
        self._levels = np.asarray(levels, dtype=float)
        self._unit = 'dB'
        self._overrides = {}      # (d, HOR) -> (θ de la fuente, giro de la fuente): celdas reemplazadas por espejo
        self._sel = set()         # celdas seleccionadas (Ctrl + clic)
        self._sel_order = []     # las mismas, en el orden en que se eligieron
        self._zoom = 1.0          # zoom con la rueda del mouse
        self._cx = self._cy = None  # centro del mallado (se mueve al arrastrar / hacer zoom)
        self._drag = None
        self._scale_fixed = False      # escala fija (no cambia al cambiar de banda)
        self._scale_user = None        # (mín, máx, paso) elegidos a mano, en dB
        self._cb_press = False         # clic derecho sobre la escala de colores
        self._show_lines = True        # líneas de subdivisión del mallado
        self._press = None             # posición del clic derecho (para distinguir clic de arrastre)
        self._apply_scale()
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(460, 460))

    def set_unit(self, unit):
        if unit != getattr(self, '_unit', None):   # cambió el tipo de dato (sin calibrar / calibrado / relativo)
            self._scale_user, self._scale_fixed = None, False   # la escala fija se vuelve a definir
        self._unit = unit
        self._apply_scale()
        self.update()

    def set_source(self, source):
        self._source = source

    def set_axes(self, azimuths, thetas):
        self._az, self._th = azimuths, thetas
        self._step = _grid_step(azimuths)

    def set_onaxis(self, value_db):
        """Valor restado para nivelar al on-axis en la banda mostrada (dB); sólo se muestra en el hover."""
        self._onaxis = value_db

    def set_corr(self, corr_by_giro):
        """Corrección aplicada por giro (dict giro→dB) para la banda mostrada; sólo se muestra en el hover."""
        self._corr = corr_by_giro

    def set_levels(self, levels):
        """Cambia la banda mostrada (recalcula las celdas y la escala de color)."""
        self._levels = np.asarray(levels, dtype=float)
        self._recalc()

    def _recalc(self):
        self._cells = radial_cells(self._levels, self._az, self._th, self._overrides)
        self._apply_scale()
        self.update()

    def band_changed(self):
        """Cambio de banda: sin 'Fija' la escala vuelve a la de los datos; con 'Fija' se conserva."""
        if not self._scale_fixed:
            self._scale_user = None
        self._apply_scale()

    def _apply_scale(self):
        """Mín y máx de la escala: fijos si el usuario los eligió, si no, los de los datos."""
        if self._scale_user is not None:
            self._vmin, self._vmax = self._scale_user[0], self._scale_user[1]
            return
        vals = [v for v, _ in self._cells.values()]
        self._vmin = min(vals) if vals else -12.0
        self._vmax = max(vals) if vals else 0.0

    def _cbar_rect(self):
        """Zona de la escala de colores (barra y valores), en coordenadas del widget."""
        x = self.width() - 78
        return QRectF(x - 40, 14, 22 + 90, self.height() - 40 - 14)

    def _edit_scale(self):
        """Diálogo de la escala: mínimo, máximo, paso (dB) como texto y si queda fija."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Escala de colores")
        form = QFormLayout(dlg)
        step0 = (self._vmax - self._vmin) / 12 if self._vmax > self._vmin else 1.0
        if self._scale_user is not None:
            step0 = self._scale_user[2]
        def field(v):
            le = QLineEdit(f"{float(v):g}")
            le.setValidator(QDoubleValidator(-300.0, 300.0, 3, le))
            le.setFixedWidth(90)
            return le
        e_min, e_max, e_step = field(self._vmin), field(self._vmax), field(step0)
        chk = QCheckBox("Fija (conservar al cambiar de banda)"); chk.setChecked(self._scale_fixed)
        form.addRow("Valor mínimo (dB):", e_min)
        form.addRow("Valor máximo (dB):", e_max)
        form.addRow("Paso por color (dB):", e_step)
        form.addRow(chk)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        auto = btns.addButton("Automática", QDialogButtonBox.ButtonRole.ResetRole)
        pulsado = {"auto": False}
        def _auto():
            pulsado["auto"] = True
            dlg.accept()
        auto.clicked.connect(_auto)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        res = dlg.exec()
        if pulsado["auto"]:
            self._scale_fixed, self._scale_user = False, None
        elif res == QDialog.DialogCode.Accepted:
            try:
                lo, hi, st = float(e_min.text()), float(e_max.text()), float(e_step.text())
            except ValueError:
                return
            if hi <= lo or st <= 0:
                return
            self._scale_user = (lo, hi, st)
            self._scale_fixed = chk.isChecked()
        else:
            return
        self._recalc()   # recalcula los colores de las celdas con la escala nueva y redibuja

    @staticmethod
    def _mirror_source(key):
        """Fuente espejo izquierda-derecha: HOR h ≤ 180 ← del micrófono de atrás en el giro 180 − h;
        HOR h > 180 ← del micrófono de delante en el giro 360 − h."""
        d, h = key
        if h <= 180:
            return (90.0 + d, 180.0 - h)
        return (90.0 - d, 360.0 - h)

    def replace_selected_mirror(self):
        n = 0
        for key in list(self._sel):
            if key[0] == 0 or key[1] is None:
                continue
            src = self._mirror_source(key)
            if any(abs(float(a) - src[1]) < 0.5 for a in self._az):
                self._overrides[key] = src; n += 1
        self._clear_sel(); self._recalc()
        return n

    def undo_selected(self):
        n = 0
        for key in list(self._sel):
            if self._overrides.pop(key, None) is not None:
                n += 1
        self._clear_sel(); self._recalc()
        return n

    def _clear_sel(self):
        self._sel.clear(); self._sel_order.clear()

    def ordered_keys(self):
        return list(self._sel_order)

    def set_overrides(self, mapping):
        """mapping: {(d, HOR): (θ fuente, giro fuente)} — reemplazos pendientes (se muestran en morado)."""
        self._overrides = dict(mapping)
        self._recalc()

    def mirror_map(self, keys):
        out = {}
        for k in keys:
            if k[0] != 0 and k[1] is not None:
                out[k] = self._mirror_source(k)
        return out

    def clear_selection(self):
        self._clear_sel(); self.update()

    def selected_pairs(self):
        """(θ, giro) de la medición que representa cada celda seleccionada (la primera si hay dos)."""
        out = []
        for key in list(self._sel_order):
            if key in self._cells:
                t, g, _ = self._cells[key][1][0]
                out.append((float(t), float(g)))
        return out

    def pending_pairs(self):
        """Reemplazos a aplicar al audio: (θ destino, giro destino, θ fuente, giro fuente).
        Destino: HOR h ≤ 180 → (90 − d, h); HOR h > 180 → (90 + d, h − 180)."""
        out = []
        for (d, h), (t_src, g_src) in self._overrides.items():
            t_dst, g_dst = (90.0 - d, h) if h <= 180 else (90.0 + d, h - 180.0)
            out.append((t_dst, g_dst, t_src, g_src))
        return out

    def gain_pairs(self):
        """Celdas seleccionadas con su simétrica: (θ destino, giro destino, θ fuente, giro fuente), mismas
        reglas que el reemplazo por espejo. Sirve para igualar la ganancia del destino a la de su simétrica."""
        out = []
        for key in list(self._sel_order):
            if key not in self._cells:
                continue
            d, h = key
            t_src, g_src = self._mirror_source(key)
            t_dst, g_dst = (90.0 - d, h) if h <= 180 else (90.0 + d, h - 180.0)
            out.append((t_dst, g_dst, t_src, g_src))
        return out

    def clear_overrides(self):
        self._overrides.clear(); self._clear_sel(); self._recalc()

    def _geom(self):
        if self._cx is None:
            self._cx, self._cy = self.width() / 2, self.height() / 2 + 6
        return self._cx, self._cy, min(self.width(), self.height()) * 0.42 * self._zoom

    def wheelEvent(self, ev):
        factor = 1.2 if ev.angleDelta().y() > 0 else 1 / 1.2
        new_zoom = min(8.0, max(0.5, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        cx, cy, R = self._geom()
        px, py = ev.position().x(), ev.position().y()
        wx, wy = (px - cx) / R, (py - cy) / R             # punto bajo el cursor, en unidades del mallado
        self._zoom = new_zoom
        R2 = min(self.width(), self.height()) * 0.42 * self._zoom
        self._cx, self._cy = px - wx * R2, py - wy * R2   # el punto bajo el cursor no se mueve
        self.update()

    def mouseDoubleClickEvent(self, ev):
        self._zoom = 1.0; self._cx = self._cy = None
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            if self._cbar_rect().contains(ev.position()):
                self._cb_press = True
                return
            self._drag = ev.position(); self._press = ev.position()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:   # Ctrl + clic: seleccionar celda
            key = self._key_at(ev.position())
            if key and key in self._cells and key[0] != 0:
                if key in self._sel:
                    self._sel.discard(key); self._sel_order.remove(key)
                else:
                    self._sel.add(key); self._sel_order.append(key)
                self.update()
            return
        self._click_at(ev)

    def mouseReleaseEvent(self, ev):
        if self._cb_press:
            self._cb_press = False
            self._edit_scale()
            return
        if self._drag is not None and self._press is not None:
            d = ev.position() - self._press
            if abs(d.x()) + abs(d.y()) < 4:          # clic sin arrastrar: menú
                self._drag = None
                self._menu_mesh(ev.globalPosition().toPoint())
                return
        self._drag = None

    def _menu_mesh(self, gpos):
        menu = QMenu(self)
        act = menu.addAction("Líneas de subdivisión")
        act.setCheckable(True); act.setChecked(self._show_lines)
        if menu.exec(gpos) is act:
            self._show_lines = not self._show_lines
            self.update()

    def _color(self, v):
        t = min(1.0, max(0.0, (v - self._vmin) / ((self._vmax - self._vmin) or 1.0)))
        return QColor.fromRgbF(t, 0.15, 1.0 - t)

    def _key_at(self, pos):
        cx, cy, R = self._geom()
        dx, dy = pos.x() - cx, pos.y() - cy
        r = math.hypot(dx, dy)
        if r > R:
            return None
        st = self._step
        if r < (st / 2.0) / 90.0 * R:
            return (0, None)
        d = max(st, min(90, int(round(r / R * 90 / st)) * st))
        hor = int(round(math.degrees(math.atan2(-dx, -dy)) % 360 / st)) * st % 360
        return (d, hor)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, R = self._geom()
        r_of = lambda d: d / 90.0 * R
        # esqueleto: todas las celdas del mallado, con o sin dato
        p.setPen(QPen(QColor('#bdbdbd'), 0.5) if self._show_lines else Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor('#ffffff')))
        st, hf = self._step, self._step / 2.0
        for d in range(st, 91, st):
            for hor in range(0, 360, st):
                if (d, hor) in self._cells:
                    continue
                d1, d2 = d - hf, min(90, d + hf)
                m1, m2 = 90 + (hor - hf), 90 + (hor + hf)
                outer = QRectF(cx - r_of(d2), cy - r_of(d2), 2 * r_of(d2), 2 * r_of(d2))
                inner = QRectF(cx - r_of(d1), cy - r_of(d1), 2 * r_of(d1), 2 * r_of(d1))
                pp = QPainterPath(); pp.arcMoveTo(outer, m1); pp.arcTo(outer, m1, float(st))
                pp.arcTo(inner, m2, -float(st)); pp.closeSubpath()
                p.drawPath(pp)
        if (0, None) not in self._cells:
            p.setPen(QPen(QColor('#bdbdbd'), 0.5) if self._show_lines else Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor('#ffffff')))
            p.drawEllipse(QPointF(cx, cy), r_of(5), r_of(5))
        for key, (v, ms) in self._cells.items():
            if key[0] == 0:
                # cénit: promedio energético de los giros; se marca si la dispersión supera el umbral
                p.setBrush(QBrush(self._color(v)))
                if key in self._sel:
                    cc = QPainterPath(); cc.addEllipse(QPointF(cx, cy), r_of(5), r_of(5))
                    _halo(p, cc, '#ffd400', 3.6, 3.0)            # selección: amarillo
                    p.setPen(Qt.PenStyle.NoPen); p.drawPath(cc)
                else:
                    p.setPen(QPen(QColor('#555'), 1)); p.drawEllipse(QPointF(cx, cy), r_of(5), r_of(5))
                continue
            d, hor = key
            d1, d2 = d - hf, min(90, d + hf)
            m1, m2 = 90 + (hor - hf), 90 + (hor + hf)
            outer = QRectF(cx - r_of(d2), cy - r_of(d2), 2 * r_of(d2), 2 * r_of(d2))
            inner = QRectF(cx - r_of(d1), cy - r_of(d1), 2 * r_of(d1), 2 * r_of(d1))
            pp = QPainterPath(); pp.arcMoveTo(outer, m1); pp.arcTo(outer, m1, float(st))
            pp.arcTo(inner, m2, -float(st)); pp.closeSubpath()
            p.setBrush(QBrush(self._color(v)))
            if key in self._sel:
                _halo(p, pp, '#ffd400', 3.6, 3.0)              # selección: amarillo, borde apenas más grueso
            elif key in self._overrides:
                p.setPen(QPen(QColor('#7b2cbf'), 2.5)); p.drawPath(pp)
                continue
            else:
                p.setPen(QPen(QColor('#ffffff'), 0.5) if self._show_lines else Qt.PenStyle.NoPen); p.drawPath(pp)
                continue
            p.setPen(Qt.PenStyle.NoPen); p.drawPath(pp)
        p.setPen(QPen(QColor('#444'), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        for hor in range(0, 360, 30):
            t = math.radians(hor)
            p.drawText(QPointF(cx - (R + 22) * math.sin(t) - 12, cy - (R + 22) * math.cos(t) + 4), f"{hor}°")
        self._paint_colorbar(p)
        p.setFont(QFont('Segoe UI', 9))
        p.drawText(QPointF(12, self.height() - 12), f"amarillo = selección · violeta = reemplazo · unidad: {self._unit}")
        p.end()

    def _paint_colorbar(self, p):
        """Escala de color con pasos: N bandas de igual tamaño entre el mínimo y el máximo, cada una con
        su color, marcas y valor en cada borde. Se ve siempre, a la derecha del mallado."""
        vmin, vmax = self._vmin, self._vmax
        if vmax - vmin < 1e-9:
            vmax = vmin + 1.0
        N = max(1, round((vmax - vmin) / self._scale_user[2])) if self._scale_user else 12
        x, w = self.width() - 78, 22
        top, bottom = 56, self.height() - 40
        hstep = (bottom - top) / N
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold)); p.setPen(QColor('#111'))
        p.drawText(QRectF(x - 40, 14, w + 90, 20), Qt.AlignmentFlag.AlignCenter, self._unit)
        for i in range(N):
            v_mid = vmax - (i + 0.5) * (vmax - vmin) / N            # arriba = máximo
            p.setPen(QPen(QColor('#666'), 0.5))
            p.setBrush(QBrush(self._color(v_mid)))
            p.drawRect(QRectF(x, top + i * hstep, w, hstep))
        # valor en cada frontera entre colores (el máximo arriba y el mínimo abajo incluidos), con su marca
        bounds = [vmax - i * (vmax - vmin) / N for i in range(N + 1)]
        fmt = "{:.0f}" if all(abs(v - round(v)) < 1e-6 for v in bounds) else "{:.1f}"
        p.setPen(QPen(QColor('#444'), 1))
        for i in range(N + 1):
            y = top + i * hstep
            p.drawLine(QPointF(x + w, y), QPointF(x + w + 4, y))
        p.setFont(QFont('Segoe UI', 8)); p.setPen(QColor('#111'))
        for i, v in enumerate(bounds):
            y = top + i * hstep
            p.drawText(QRectF(x + w + 6, y - 8, 40, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fmt.format(v))

    def mouseMoveEvent(self, ev):
        if self._drag is not None:                        # arrastre con botón derecho: mover el mallado
            d = ev.position() - self._drag
            self._cx += d.x(); self._cy += d.y()
            self._drag = ev.position()
            self.update()
            return
        key = self._key_at(ev.position())
        if key is None or key not in self._cells:
            QToolTip.hideText(); return
        v, ms = self._cells[key]
        lines = [f"d={key[0]}°" + ("" if key[1] is None else f" · HOR {key[1]}°"), f"valor (energía): {v:.1f} dB"]
        corr = getattr(self, '_corr', None)
        for t, g, dbv in ms:
            k = int(round(t / 10)) + 1
            extra = '' if not corr or g not in corr else f" · corrección toma {corr[g]:+.2f} dB"
            nombre = f"mic_{k}_ang_forte_{int(g)}.wav" if self._step == 10 else "celda interpolada"
            lines.append(f"  {nombre} · θ={t:.0f}° · giro {g:.0f}° → {dbv:.1f} dB{extra}")
        if key in self._overrides:
            t_src, g_src = self._overrides[key]
            lines.append(f"↔ reemplazada por espejo: θ={t_src:.0f}° · giro {g_src:.0f}°")
        onax = getattr(self, '_onaxis', None)
        if onax is not None:
            lines.append(f"nivelado al on-axis: −{onax:.2f} dB (nivel on-axis antes de nivelar)")
        if len(ms) > 1 and (max(m[2] for m in ms) - min(m[2] for m in ms)) > THR_DB:
            lines.append(f"⚠ diferencia > {THR_DB:g} dB entre mediciones")
        QToolTip.showText(ev.globalPosition().toPoint(), chr(10).join(lines), self)

    def _click_at(self, ev):
        key = self._key_at(ev.position())
        if key and key in self._cells and self._on_click is not None:
            _, ms = self._cells[key]
            t, g, _ = ms[0]
            msg = self._on_click(float(g), float(t))
            if msg:
                QToolTip.showText(ev.globalPosition().toPoint(), msg, self)


def _fmt_ms(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


class _PlayerBar(QWidget):
    """Barra de reproducción estándar: play/pausa, deslizador de posición y tiempo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSlider
        from PyQt6.QtMultimedia import QMediaPlayer
        from ui.audio_play import player
        self._pl = player()
        self._btn = QPushButton("▶")
        self._btn.setFixedWidth(36)
        self._btn.clicked.connect(self._toggle)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.sliderMoved.connect(self._pl.setPosition)
        self._time = QLabel("00:00 / 00:00")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._btn)
        row.addWidget(self._slider, 1)
        row.addWidget(self._time)
        self._pl.positionChanged.connect(self._on_pos)
        self._pl.durationChanged.connect(self._on_dur)
        self._pl.playbackStateChanged.connect(self._on_state)

    def _toggle(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._pl.pause()
        else:
            self._pl.play()

    def _on_pos(self, ms):
        if not self._slider.isSliderDown():
            self._slider.setValue(ms)
        self._time.setText(f"{_fmt_ms(ms)} / {_fmt_ms(self._pl.duration())}")

    def _on_dur(self, ms):
        self._slider.setRange(0, ms)
        self._time.setText(f"{_fmt_ms(self._pl.position())} / {_fmt_ms(ms)}")

    def _on_state(self, st):
        from PyQt6.QtMultimedia import QMediaPlayer
        self._btn.setText("❚❚" if st == QMediaPlayer.PlaybackState.PlayingState else "▶")


class MatrixPanel(QWidget):
    def __init__(self, levels3d, azimuths, thetas, freqs, source=None, on_click=None, apply_cb=None,
                 undo_cb=None, gain_cb=None, unit='dB', corr=None, onaxis=None, parent=None):
        super().__init__(parent)
        self._undo_cb = undo_cb
        self._gain_cb = gain_cb
        self._onaxis = None if onaxis is None else np.asarray(onaxis, dtype=float)
        self._corr = None if corr is None else np.asarray(corr, dtype=float)
        self._apply_cb = apply_cb
        self._unit = unit
        self._levels3d = np.asarray(levels3d, dtype=float)
        self._az, self._th, self._freqs, self._source = azimuths, thetas, freqs, source
        lay = QVBoxLayout(self)
        if isinstance(source, dict):
            origin = "archivos WAV de audio (uno por toma)"
        else:
            origin = os.path.basename(source) if source else "cálculo desde audio"
        top = QHBoxLayout()
        self._top_row = top
        flabel = QLabel("Frecuencia:")
        flabel.setStyleSheet("font-weight: bold;")
        top.addWidget(flabel)
        self._combo = QComboBox()
        for i, f in enumerate(freqs):
            from core.data_store import freq_label
            self._combo.addItem("RMS total (sin banda)" if f is None else f"{freq_label(f)} Hz", i)
        self._combo.currentIndexChanged.connect(self._on_band)
        top.addWidget(self._combo)
        top.addStretch(1)
        lay.addLayout(top)
        self._status = QLabel("")
        lay.addWidget(self._status)
        def _click(g, t):
            msg = on_click(g, t) if on_click is not None else ""
            self._status.setText(msg or "")
            return msg
        self._on_click_cb = _click if on_click else None
        self._radial = _Radial(self._levels3d[:, :, 0], azimuths, thetas, source, on_click=self._on_click_cb)
        self._radial.set_unit(unit)
        self._radial.set_corr(self._corr_for_band(0))
        self._radial.set_onaxis(self._onaxis_for_band(0))
        lay.addWidget(self._radial, 1)
        bar = QHBoxLayout()
        self._b_rep = QPushButton("Reemplazar…")
        self._b_rep.setToolTip("Ctrl + clic en las celdas a reemplazar (en orden). Luego: Reemplazar.")
        self._b_rep.clicked.connect(self._on_replace_btn)
        bar.addWidget(self._b_rep)
        self._b_gain = QPushButton("Corregir ganancia")
        self._b_gain.setToolTip("Iguala la ganancia de las celdas seleccionadas (Ctrl + clic) a la de su simétrica. "
                                "Modifica los WAV de la carpeta de audios y deja una copia de los originales en la subcarpeta "
                                "Originales_respaldo. Ctrl+Z lo deshace.")
        self._b_gain.clicked.connect(self._on_gain_btn)
        bar.addWidget(self._b_gain)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._pick_dest = None        # modo "Elegir tomas": celdas a reemplazar (en orden)
        self._menu = None
        if on_click is not None:
            lay.addWidget(_PlayerBar())
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo_key)
        self._update_title()

    def _open_menu(self):
        ReplaceMenu(self).exec()

    def _sync_button(self):
        """El botón de abajo: 'Aplicar Reemplazo' si hay reemplazos listos, si no 'Reemplazar…'."""
        ready = bool(self._radial._overrides)
        self._b_rep.setText("Aplicar Reemplazo" if ready else "Reemplazar…")
        # Verde cuando hay reemplazos listos para aplicar, así se nota que falta ese paso.
        self._b_rep.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; font-weight:bold; }"
            "QPushButton:hover { background:#36913a; }" if ready else "")

    def _menu_choice(self, mode):
        """Elegido en el menú (cierra solo). 'Simétrico' aplica el espejo a la selección actual;
        'Elegir tomas' guarda la selección como destino y espera las tomas de origen."""
        if mode == 'mirror':
            keys = self._radial.ordered_keys()
            if not keys:
                self._status.setText("Seleccioná las celdas a reemplazar (Ctrl + clic), y después elegí Simétrico."); return
            self._radial.set_overrides(self._radial.mirror_map(keys))
            self._radial.clear_selection()
            self._status.setText(f"{len(keys)} celdas con simétrico listas. Tocá Aplicar Reemplazo.")
        else:
            keys = self._radial.ordered_keys()
            if not keys:
                self._status.setText("Seleccioná primero las celdas a reemplazar (Ctrl + clic), y después elegí Elegir tomas."); return
            self._pick_dest = keys
            self._radial.clear_selection()
            self._status.setText(f"Destino: {len(keys)} celdas. Ahora Ctrl + clic en las tomas de origen, en orden, y tocá Reemplazar…")
        self._sync_button()

    def _on_gain_btn(self):
        pairs = self._radial.gain_pairs()
        if not pairs:
            self._status.setText("Seleccioná las celdas a corregir (Ctrl + clic).")
            return
        if self._gain_cb is None:
            return
        msg = self._gain_cb(pairs)
        if msg:
            self._status.setText(msg)

    def _on_replace_btn(self):
        if self._radial._overrides:
            self._apply_pending(); return
        if self._pick_dest is not None:
            src = self._radial.ordered_keys()
            if len(src) != len(self._pick_dest):
                self._status.setText(f"Hay {len(self._pick_dest)} destinos y {len(src)} orígenes: tienen que coincidir."); return
            mapping = {dst: self._source_of(sk) for dst, sk in zip(self._pick_dest, src)}
            self._radial.set_overrides(mapping)
            self._radial.clear_selection()
            self._status.setText(f"{len(mapping)} reemplazos listos (orden de selección). Tocá Aplicar Reemplazo.")
            self._sync_button(); return
        self._open_menu()

    def _source_of(self, key):
        """(θ, giro) de la toma de origen elegida en la matriz (su primera medición)."""
        t, g, _ = self._radial._cells[key][1][0]
        return (float(t), float(g))

    def _apply_pending(self):
        pairs = self._radial.pending_pairs()
        if not pairs:
            self._status.setText("No hay reemplazos pendientes."); return False
        if self._apply_cb is None:
            self._status.setText("No hay audio cargado para aplicar."); return False
        n = self._apply_cb(pairs)
        self._radial.clear_overrides()
        self._pick_dest = None
        self._sync_button()
        self._status.setText(n if isinstance(n, str) else f"Aplicados {len(pairs)} reemplazos al audio.")
        return True

    def _undo_key(self):
        if self._radial._overrides:                           # pendientes: se descartan
            self._radial.clear_overrides(); self._pick_dest = None
            self._status.setText("Reemplazos pendientes descartados.")
        elif self._undo_cb is not None:                       # aplicados: se deshace el último lote
            self._status.setText(self._undo_cb())

    def _update_title(self):
        i = self._combo.currentData() or 0
        f = self._freqs[i]
        from core.data_store import freq_label
        self.setWindowTitle("Matriz radial — " + ("RMS total" if f is None else f"{freq_label(f)} Hz"))

    def _corr_for_band(self, i):
        """dict giro→dB de la corrección aplicada en la banda i (o None si no hubo Aplicar)."""
        if self._corr is None or i >= self._corr.shape[1]:
            return None
        # la corrección viene de los giros medidos (0..180 en pasos iguales); la grilla puede ser más fina
        corr_az = np.linspace(0.0, 180.0, self._corr.shape[0])
        out = {}
        for a in self._az:
            k = int(np.argmin(np.abs(corr_az - float(a))))
            out[int(round(float(a)))] = float(self._corr[k, i])
        return out

    def _onaxis_for_band(self, i):
        if self._onaxis is None or i >= len(self._onaxis):
            return None
        return float(self._onaxis[i])

    def refresh(self, levels3d, azimuths, thetas, freqs, source=None, unit='dB', corr=None, onaxis=None):
        self._onaxis = None if onaxis is None else np.asarray(onaxis, dtype=float)
        """Actualiza la matriz con los datos nuevos (filtro, calibración, reemplazos, cálculo)."""
        self._corr = None if corr is None else np.asarray(corr, dtype=float)
        self._levels3d = np.asarray(levels3d, dtype=float)
        self._az, self._th, self._freqs, self._source = azimuths, thetas, freqs, source
        self._unit = unit
        cur = self._combo.currentData() or 0
        self._combo.blockSignals(True)
        self._combo.clear()
        from core.data_store import freq_label
        for i, f in enumerate(freqs):
            self._combo.addItem("RMS total (sin banda)" if f is None else f"{freq_label(f)} Hz", i)
        self._combo.setCurrentIndex(min(cur, self._combo.count() - 1))
        self._combo.blockSignals(False)
        self._radial.set_source(source)
        self._radial.set_unit(unit)
        self._radial.set_axes(azimuths, thetas)
        self._radial.set_levels(self._levels3d[:, :, self._combo.currentData() or 0])

    def set_leading_widget(self, w):
        """Pone un widget (el selector de Vista) al comienzo de la fila de Frecuencia."""
        if w.parent() is not self and w.parent() is not None:
            w.setParent(None)
        if self._top_row.indexOf(w) < 0:
            self._top_row.insertWidget(0, w)
        w.show()

    def _on_band(self, _=None):
        i = self._combo.currentData() or 0
        self._radial.set_corr(self._corr_for_band(i))
        self._radial.set_onaxis(self._onaxis_for_band(i))
        self._radial.band_changed()
        self._radial.set_axes(self._az, self._th)   # el mallado puede ser de 5° (interpolado)
        self._radial.set_levels(self._levels3d[:, :, i])
        self._update_title()


class ReplaceMenu(QDialog):
    """Menú del botón Reemplazar: dos opciones. Al elegir una, el menú se cierra."""
    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self.setWindowTitle("Reemplazar por")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Reemplazar por:"))
        b_sim = QPushButton("Simétrico")
        b_sim.setToolTip("Cada celda seleccionada toma su medición espejo izquierda-derecha.")
        b_sim.clicked.connect(lambda: self._choose('mirror'))
        lay.addWidget(b_sim)
        b_pick = QPushButton("Elegir tomas")
        b_pick.setToolTip("Las celdas seleccionadas son el destino; después elegís las tomas de origen, en orden.")
        b_pick.clicked.connect(lambda: self._choose('pick'))
        lay.addWidget(b_pick)

    def _choose(self, mode):
        self.accept()
        self._owner._menu_choice(mode)
