"""ui/matrix_dialog.py — Herramientas ▸ Matriz radial: mallado de mediciones (anillo = distancia al cénit,
sector = HOR). Cada celda muestra el nivel que le corresponde según la regla de simetría."""
import math
import os
import numpy as np
from PyQt6.QtCore import Qt, QSize, QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QDialogButtonBox,
                             QToolTip, QPushButton, QComboBox)

THR_DB = 3.0   # diferencia máxima entre mediciones de una misma celda antes de marcarla


def _energy_mean(values):
    v = np.asarray(values, dtype=float)
    return float(10 * np.log10(np.mean(10 ** (v / 10.0))))


def radial_cells(levels, azimuths, thetas, overrides=None):
    """Devuelve {(d, hor): (valor, [(θ, giro, dB), ...])} con la regla de la matriz radial:
    d = |θ − 90°| (anillo), hor = giro/HOR de 10°. Delante (θ = 90 − d) mide HOR = giro;
    atrás (θ = 90 + d) mide HOR = giro + 180. En HOR 0° y 180° hay dos mediciones: se promedian
    en energía. El cénit (d = 0) promedia los giros de θ = 90°."""
    L = np.asarray(levels, dtype=float)
    az = [float(a) for a in azimuths]
    th = [float(t) for t in thetas]
    def get(giro, t):
        ia = [i for i, a in enumerate(az) if abs(a - giro) < 0.5]
        it = [j for j, x in enumerate(th) if abs(x - t) < 0.5]
        return (L[ia[0], it[0]], giro, t) if ia and it and np.isfinite(L[ia[0], it[0]]) else None
    cells = {}
    cen = [get(g, 90.0) for g in az]
    cen = [c for c in cen if c]
    if cen:
        cells[(0, None)] = (_energy_mean([c[0] for c in cen]), [(c[2], c[1], c[0]) for c in cen])
    for d in range(10, 91, 10):
        tf, tb = 90.0 - d, 90.0 + d
        for hor in range(0, 360, 10):
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
        self._cells = radial_cells(levels, azimuths, thetas)
        self._source = source
        self._on_click = on_click
        self._levels = np.asarray(levels, dtype=float)
        self._overrides = {}      # (d, HOR) -> (θ de la fuente, giro de la fuente): celdas reemplazadas por espejo
        self._sel = set()         # celdas seleccionadas (Ctrl + clic)
        self._zoom = 1.0          # zoom con la rueda del mouse
        self._cx = self._cy = None  # centro del mallado (se mueve al arrastrar / hacer zoom)
        self._drag = None
        vals = [v for v, _ in self._cells.values()]
        self._vmin = min(vals) if vals else -12.0
        self._vmax = max(vals) if vals else 0.0
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(460, 460))

    def set_levels(self, levels):
        """Cambia la banda mostrada (recalcula las celdas y la escala de color)."""
        self._levels = np.asarray(levels, dtype=float)
        self._recalc()

    def _recalc(self):
        self._cells = radial_cells(self._levels, self._az, self._th, self._overrides)
        vals = [v for v, _ in self._cells.values()]
        self._vmin = min(vals) if vals else -12.0
        self._vmax = max(vals) if vals else 0.0
        self.update()

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
        self._sel.clear(); self._recalc()
        return n

    def undo_selected(self):
        n = 0
        for key in list(self._sel):
            if self._overrides.pop(key, None) is not None:
                n += 1
        self._sel.clear(); self._recalc()
        return n

    def clear_selection(self):
        self._sel.clear(); self.update()

    def selected_pairs(self):
        """(θ, giro) de la medición que representa cada celda seleccionada (la primera si hay dos)."""
        out = []
        for key in sorted(self._sel, key=lambda k: (k[0], k[1] or 0)):
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

    def clear_overrides(self):
        self._overrides.clear(); self._sel.clear(); self._recalc()

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
            self._drag = ev.position()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:   # Ctrl + clic: seleccionar celda
            key = self._key_at(ev.position())
            if key and key in self._cells and key[0] != 0:
                self._sel ^= {key}
                self.update()
            return
        self._click_at(ev)

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def _color(self, v):
        t = min(1.0, max(0.0, (v - self._vmin) / ((self._vmax - self._vmin) or 1.0)))
        return QColor.fromRgbF(t, 0.15, 1.0 - t)

    def _key_at(self, pos):
        cx, cy, R = self._geom()
        dx, dy = pos.x() - cx, pos.y() - cy
        r = math.hypot(dx, dy)
        if r > R:
            return None
        if r < 5 / 90.0 * R:
            return (0, None)
        d = max(10, min(90, int(round(r / R * 90 / 10)) * 10))
        hor = int(round(math.degrees(math.atan2(-dx, -dy)) % 360 / 10)) * 10 % 360
        return (d, hor)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, R = self._geom()
        r_of = lambda d: d / 90.0 * R
        for key, (v, ms) in self._cells.items():
            if key[0] == 0:
                # cénit: promedio energético de los giros; se marca si la dispersión supera el umbral
                flag = len(ms) > 1 and (max(m[2] for m in ms) - min(m[2] for m in ms)) > THR_DB
                p.setPen(QPen(QColor('#d62728') if flag else QColor('#555'), 2 if flag else 1))
                p.setBrush(QBrush(self._color(v)))
                p.drawEllipse(QPointF(cx, cy), r_of(5), r_of(5))
                continue
            d, hor = key
            d1, d2 = d - 5, min(90, d + 5)
            m1, m2 = 90 + (hor - 5), 90 + (hor + 5)
            outer = QRectF(cx - r_of(d2), cy - r_of(d2), 2 * r_of(d2), 2 * r_of(d2))
            inner = QRectF(cx - r_of(d1), cy - r_of(d1), 2 * r_of(d1), 2 * r_of(d1))
            pp = QPainterPath(); pp.arcMoveTo(outer, m1); pp.arcTo(outer, m1, 10.0)
            pp.arcTo(inner, m2, -10.0); pp.closeSubpath()
            flag = len(ms) > 1 and (max(m[2] for m in ms) - min(m[2] for m in ms)) > THR_DB
            if key in self._sel:
                pen = QPen(QColor('#ffd400'), 3)
            elif key in self._overrides:
                pen = QPen(QColor('#7b2cbf'), 2.5)
            else:
                pen = QPen(QColor('#d62728') if flag else QColor('#ffffff'), 2 if flag else 0.5)
            p.setPen(pen)
            p.setBrush(QBrush(self._color(v)))
            p.drawPath(pp)
        # nombre del archivo de cada medición dentro de la celda (tamaño ajustado a la celda)
        for key, (v, ms) in self._cells.items():
            names = [f"mic_{int(round(t / 10)) + 1}_ang_forte_{int(g)}.wav" for t, g, _ in ms]
            if key[0] == 0:
                rm, arc, dr = 2.5 / 90.0 * R, 5 / 90.0 * R * 2, 5 / 90.0 * R * 2
                mid = 0.0
                names = ["mic_10 · promedio de los giros"]
            else:
                d, hor = key
                rm = d / 90.0 * R
                arc = rm * math.radians(10)
                dr = 10 / 90.0 * R
                mid = math.radians(90 + hor)
            cxm, cym = (cx + rm * math.cos(mid), cy - rm * math.sin(mid)) if key[0] else (cx, cy)
            longest = max(len(n) for n in names)
            fs = min(9.0, min(arc, dr) / (0.62 * longest / max(len(names), 1)) if len(names) == 1 else min(arc, dr) / (0.62 * longest) / len(names))
            if fs < 4:
                continue
            p.setFont(QFont('Segoe UI', max(4, int(fs)))); p.setPen(QColor('#111'))
            lh = fs * 1.25
            y0 = cym - lh * (len(names) - 1) / 2
            for i, n in enumerate(names):
                p.drawText(QRectF(cxm - 200, y0 + i * lh - lh / 2, 400, lh), Qt.AlignmentFlag.AlignCenter, n)
        p.setPen(QPen(QColor('#444'), 1, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        for d in range(10, 91, 10):
            p.drawEllipse(QPointF(cx, cy), r_of(d), r_of(d))
        p.setFont(QFont('Segoe UI', 8)); p.setPen(QColor('#111'))
        for d in range(10, 91, 10):
            p.drawText(QPointF(cx + 4, cy - r_of(d) - 2), f"d={d}°")
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        for hor in range(0, 360, 30):
            t = math.radians(hor)
            p.drawText(QPointF(cx - (R + 22) * math.sin(t) - 12, cy - (R + 22) * math.cos(t) + 4), f"{hor}°")
        p.setFont(QFont('Segoe UI', 9))
        p.drawText(QPointF(12, self.height() - 12), f"Colores: {self._vmin:.1f} a {self._vmax:.1f} dB · rojo = diferencia > {THR_DB:g} dB entre mediciones")
        p.end()

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
        for t, g, dbv in ms:
            lines.append(f"  θ={t:.0f}° · giro {g:.0f}° → {dbv:.1f} dB")
        if key in self._overrides:
            t_src, g_src = self._overrides[key]
            lines.append(f"↔ reemplazada por espejo: θ={t_src:.0f}° · giro {g_src:.0f}°")
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


class MatrixDialog(QDialog):
    def __init__(self, levels3d, azimuths, thetas, freqs, source=None, on_click=None, apply_cb=None,
                 compare_cb=None, parent=None):
        super().__init__(parent)
        self._apply_cb = apply_cb
        self._compare_cb = compare_cb
        self.resize(780, 720)
        self._levels3d = np.asarray(levels3d, dtype=float)
        self._az, self._th, self._freqs, self._source = azimuths, thetas, freqs, source
        lay = QVBoxLayout(self)
        if isinstance(source, dict):
            origin = "archivos WAV de audio (uno por toma)"
        else:
            origin = os.path.basename(source) if source else "cálculo desde audio"
        top = QHBoxLayout()
        top.addWidget(QLabel("Frecuencia:"))
        self._combo = QComboBox()
        for i, f in enumerate(freqs):
            from core.data_store import freq_label
            self._combo.addItem("RMS total (sin banda)" if f is None else f"{freq_label(f)} Hz", i)
        self._combo.currentIndexChanged.connect(self._on_band)
        top.addWidget(self._combo)
        top.addStretch(1)
        lay.addLayout(top)
        intro = QLabel(
            f"origen: {origin}. Anillo = distancia al cénit |θ − 90°|, sector = HOR (10°). "
            "Pasá el mouse para ver las mediciones de cada celda. Click: reproduce esa toma (si hay audio).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self._status = QLabel("")
        lay.addWidget(self._status)
        def _click(g, t):
            msg = on_click(g, t) if on_click is not None else ""
            self._status.setText(msg or "")
            return msg
        self._on_click_cb = _click if on_click else None
        self._radial = _Radial(self._levels3d[:, :, 0], azimuths, thetas, source, on_click=self._on_click_cb)
        lay.addWidget(self._radial, 1)
        bar = QHBoxLayout()
        b_mir = QPushButton("Reemplazar selección por espejo")
        b_und = QPushButton("Deshacer reemplazo")
        b_cln = QPushButton("Limpiar selección")
        b_cmp = QPushButton("Comparar selección")
        b_cmp.setToolTip("Abre la comparación de las mediciones de las celdas seleccionadas.")
        def _cmp():
            pairs = self._radial.selected_pairs()
            if not pairs:
                self._status.setText("Seleccioná celdas (Ctrl + clic) para comparar."); return
            if self._compare_cb is not None:
                self._compare_cb(pairs)
        b_cmp.clicked.connect(_cmp)
        bar.addWidget(b_cmp)
        b_app = QPushButton("Aplicar al audio (persistente)")
        b_app.setToolTip("Escribe los reemplazos en la señal de cada micrófono en memoria. Después, Calcular "
                         "usa esos datos. Se pierden al cerrar la app si no se guarda la sesión.")
        b_app.setEnabled(apply_cb is not None)
        def _apply():
            pairs = self._radial.pending_pairs()
            if not pairs:
                self._status.setText("No hay reemplazos pendientes."); return
            n = self._apply_cb(pairs)
            self._status.setText(n if isinstance(n, str) else
                                 f"Aplicados {len(pairs)} reemplazos al audio. Presioná Calcular para recalcular.")
            if not isinstance(n, str):
                self._radial.clear_overrides()
        b_app.clicked.connect(_apply)
        bar.addWidget(b_app)
        b_mir.setToolTip("Ctrl + clic selecciona celdas. Cada una se reemplaza por su medición espejo izquierda-derecha.")
        b_mir.clicked.connect(lambda: self._status.setText(f"Reemplazadas {self._radial.replace_selected_mirror()} celdas por espejo."))
        b_und.clicked.connect(lambda: self._status.setText(f"Deshechos {self._radial.undo_selected()} reemplazos."))
        b_cln.clicked.connect(self._radial.clear_selection)
        for b in (b_mir, b_und, b_cln):
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        if on_click is not None:
            lay.addWidget(_PlayerBar())
        row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        row.rejected.connect(self.reject)
        row.accepted.connect(self.accept)
        lay.addWidget(row)
        self._update_title()

    def _update_title(self):
        i = self._combo.currentData() or 0
        f = self._freqs[i]
        from core.data_store import freq_label
        self.setWindowTitle("Matriz radial — " + ("RMS total" if f is None else f"{freq_label(f)} Hz"))

    def _on_band(self, _=None):
        i = self._combo.currentData() or 0
        self._radial.set_levels(self._levels3d[:, :, i])
        self._update_title()
