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
        self._sel_order = []     # las mismas, en el orden en que se eligieron
        self._zoom = 1.0          # zoom con la rueda del mouse
        self._cx = self._cy = None  # centro del mallado (se mueve al arrastrar / hacer zoom)
        self._drag = None
        vals = [v for v, _ in self._cells.values()]
        self._vmin = min(vals) if vals else -12.0
        self._vmax = max(vals) if vals else 0.0
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(460, 460))

    def set_unit(self, unit):
        self._unit = unit
        self.update()

    def set_source(self, source):
        self._source = source

    def set_axes(self, azimuths, thetas):
        self._az, self._th = azimuths, thetas

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
            self._drag = ev.position()
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
                p.setPen(QPen(QColor('#ffd400') if flag else QColor('#555'), 2 if flag else 1))
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
                pen = QPen(QColor('#00b3ff'), 3)
            elif key in self._overrides:
                pen = QPen(QColor('#7b2cbf'), 2.5)
            else:
                pen = QPen(QColor('#ffd400') if flag else QColor('#ffffff'), 2 if flag else 0.5)
            p.setPen(pen)
            p.setBrush(QBrush(self._color(v)))
            p.drawPath(pp)
        p.setPen(QPen(QColor('#444'), 1, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        for d in range(10, 91, 10):
            p.drawEllipse(QPointF(cx, cy), r_of(d), r_of(d))
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        for hor in range(0, 360, 30):
            t = math.radians(hor)
            p.drawText(QPointF(cx - (R + 22) * math.sin(t) - 12, cy - (R + 22) * math.cos(t) + 4), f"{hor}°")
        self._paint_colorbar(p)
        p.setFont(QFont('Segoe UI', 9))
        p.drawText(QPointF(12, self.height() - 12), f"amarillo = diferencia > {THR_DB:g} dB entre mediciones · unidad: {self._unit}")
        p.end()

    def _paint_colorbar(self, p):
        """Escala de color con pasos: N bandas de igual tamaño entre el mínimo y el máximo, cada una con
        su color, marcas y valor en cada borde. Se ve siempre, a la derecha del mallado."""
        N = 12
        vmin, vmax = self._vmin, self._vmax
        if vmax - vmin < 1e-9:
            vmax = vmin + 1.0
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
        # valor de cada paso en su centro, sin decimales
        p.setFont(QFont('Segoe UI', 8)); p.setPen(QColor('#111'))
        for i in range(N):
            v_mid = vmax - (i + 0.5) * (vmax - vmin) / N
            y = top + (i + 0.5) * hstep
            p.drawText(QRectF(x + w + 6, y - 8, 40, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{v_mid:.0f}")

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
            k = int(round(t / 10)) + 1
            lines.append(f"  mic_{k}_ang_forte_{int(g)}.wav · θ={t:.0f}° · giro {g:.0f}° → {dbv:.1f} dB")
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
                 compare_cb=None, undo_cb=None, unit='dB', parent=None):
        super().__init__(parent)
        self._undo_cb = undo_cb
        self._apply_cb = apply_cb
        self._compare_cb = compare_cb
        self._unit = unit
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
        self._radial.set_unit(unit)
        lay.addWidget(self._radial, 1)
        bar = QHBoxLayout()
        self._b_rep = QPushButton("Reemplazar…")
        self._b_rep.setToolTip("Ctrl + clic en las celdas a reemplazar (en orden). Luego: Reemplazar.")
        self._b_rep.clicked.connect(self._on_replace_btn)
        bar.addWidget(self._b_rep)
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
        bar.addStretch(1)
        lay.addLayout(bar)
        self._pick_dest = None        # modo "Elegir tomas": celdas a reemplazar (en orden)
        self._menu = None
        if on_click is not None:
            lay.addWidget(_PlayerBar())
        row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        row.rejected.connect(self.reject)
        row.accepted.connect(self.accept)
        lay.addWidget(row)
        self._update_title()

    def _open_menu(self):
        ReplaceMenu(self).exec()

    def _sync_button(self):
        """El botón de abajo: 'Aplicar Reemplazo' si hay reemplazos listos, si no 'Reemplazar…'."""
        self._b_rep.setText("Aplicar Reemplazo" if self._radial._overrides else "Reemplazar…")

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

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Z and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if self._radial._overrides:                       # pendientes: se descartan
                self._radial.clear_overrides(); self._pick_dest = None
                self._status.setText("Reemplazos pendientes descartados.")
            elif self._undo_cb is not None:                   # aplicados: se deshace el último lote
                self._status.setText(self._undo_cb())
            return
        super().keyPressEvent(ev)

    def _update_title(self):
        i = self._combo.currentData() or 0
        f = self._freqs[i]
        from core.data_store import freq_label
        self.setWindowTitle("Matriz radial — " + ("RMS total" if f is None else f"{freq_label(f)} Hz"))

    def refresh(self, levels3d, azimuths, thetas, freqs, source=None, unit='dB'):
        """Actualiza la matriz con los datos nuevos (filtro, calibración, reemplazos, cálculo)."""
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

    def _on_band(self, _=None):
        i = self._combo.currentData() or 0
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
