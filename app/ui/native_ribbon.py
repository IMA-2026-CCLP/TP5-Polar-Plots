"""
ui/native_ribbon.py — Barra superior nativa estilo VituixCAD: menú + pestañas + filas de parámetros.

Reemplaza a HtmlRibbon (shell.html + QWebChannel) con widgets Qt normales, pero
conserva exactamente su API pública (señales, proxies, métodos) para que
MainWindow no cambie. `Bridge` se sigue usando como contenedor de `state` y de
los slots que arman los parámetros de cada señal (`emitPlotParams`…);
ahora los llaman los widgets directamente en vez de JS.

Los valores por defecto de los controles salen de `Bridge.state`: no se repiten acá.
"""
import json

from PyQt6.QtCore import Qt, QLocale, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QDoubleValidator
from PyQt6.QtWidgets import (
    QFormLayout, QGridLayout, QGroupBox, QInputDialog, QMenu, QMessageBox, QScrollArea, QSizePolicy, QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QTabBar, QLabel, QPushButton,
    QComboBox, QLineEdit, QFrame, QToolButton,
)

from ui.bridge import Bridge
from ui import theme as _theme

_TABS = [
    ("Procesamiento", "Visualizar señales, aplicar filtros y alinear tomas"),
    ("Directividad",  "Calcular y visualizar el patrón de directividad acústica"),
]
_GCC_HELP = '<b>¿Para qué sirve?</b><br>Al alinear los micrófonos se estima el retardo entre cada uno y el de referencia con GCC-PHAT (correlación cruzada). Este umbral pone en cero, antes de correlacionar, los tramos de la señal de referencia que están por debajo de ese nivel, para que el ruido de fondo y el silencio no falseen la estimación.<br><br><b>¿Cómo se usa?</b><br>&bull; <b>Vacío</b>: no filtra nada (valor por defecto).<br>&bull; <b>Con valor</b> (dBFS): ponelo un poco por encima del ruido de fondo, por ejemplo entre &minus;55 y &minus;40 dBFS, cerca del umbral que usaste para el onset.<br>&bull; Si es demasiado alto se descartan partes útiles del canto y la alineación empeora.<br><br>Sólo afecta a <i>Alinear micrófonos</i>. <i>Alinear tomas</i> usa el Umbral del onset.'
_CAP_W = 78   # ancho de la columna de títulos de fila (Cálculo, Vista…)


# Paletas de color de los gráficos 3D y esfera (Opciones ▸ Gráficos ▸ Paleta de colores).
PALETTES = ("RdBu v4", "Plasma", "Viridis", "Turbo", "Inferno", "Magma", "Cividis")

class _StateVal:
    """Imita QLineEdit.text() / QComboBox.currentText() leyendo Bridge.state (usado por MainWindow)."""
    def __init__(self, state: dict, key: str, default=''):
        self._s, self._k, self._d = state, key, default
    def text(self):
        return str(self._s.get(self._k, self._d))
    def currentText(self):
        return self.text()


def _num_str(v) -> str:
    """10 / 10.0 / '10' → '10' (Bridge._parse_theta espera enteros sin decimales)."""
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(v)


def _vsep() -> QFrame:
    f = QFrame()
    f.setObjectName("rb_sep")
    f.setFixedSize(1, 20)
    return f


class NativeRibbon(QWidget):
    """Drop-in de HtmlRibbon. Mismas señales y métodos públicos."""

    tab_changed       = pyqtSignal(int)
    sig_theme_toggled = pyqtSignal()

    sig_load_audio      = pyqtSignal()
    sig_edit_patterns   = pyqtSignal()
    sig_open_options    = pyqtSignal(str)     # 'polar2d' | 'spectrum' | 'sphere' | '3d' | 'images'
    sig_save_session    = pyqtSignal()
    sig_save_session_as = pyqtSignal()
    sig_load_session    = pyqtSignal()
    sig_apply_hpf        = pyqtSignal(float)
    sig_corr_recalc      = pyqtSignal()
    sig_align_takes      = pyqtSignal(float, float, object, float)
    sig_align_preview    = pyqtSignal(float, float, object)
    sig_align_ref        = pyqtSignal(object)
    sig_open_calibracion = pyqtSignal()
    sig_plot_params      = pyqtSignal(object, object, bool, bool, object, float)

    sig_detect_notes     = pyqtSignal(float, float, float, float, object)
    sig_edit_scale       = pyqtSignal()
    sig_preset_changed   = pyqtSignal(str)
    sig_save_mask        = pyqtSignal()
    sig_load_mask        = pyqtSignal()

    sig_export_all_images   = pyqtSignal()
    sig_dir_display_changed = pyqtSignal()
    sig_intersect_cut3d     = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge  = Bridge(self)
        self._b       = self._bridge
        self._loaders = []          # closures que vuelcan Bridge.state a cada widget
        self._act     = {}          # name → QAction
        self._btn     = {}          # name → QPushButton (se habilitan al cargar un tensor)
        self._wire()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._make_actions()
        lay.addWidget(self._make_menubar())
        lay.addLayout(self._make_tabbar())
        # Paneles laterales (uno por pestaña) y página de Notas: MainWindow los aloja en un dock / ventana.
        self._make_align_dialogs()
        self.notas_panel = self.build_notas_panel()
        self.proc_panel = self._panel_proc()
        self.dir_panel  = self._panel_dir()
        line = QFrame()
        line.setObjectName("rb_line")
        line.setFixedHeight(1)
        lay.addWidget(line)

        # Proxies de compatibilidad con MainWindow
        self.btn_save_mask = self._act['save_mask']
        self.combo_bands   = _StateVal(self._b.state, 'bands',  '1/3')
        self.le_ref_az     = _StateVal(self._b.state, 'ref_az', '0')
        self.le_ref_th     = _StateVal(self._b.state, 'ref_th', '0')

        self._tabs.setCurrentIndex(self._b.state['tab'])
        self._on_tab(self._tabs.currentIndex())
        self._sync()

    # ── Conexiones bridge → señales ───────────────────────────────────────
    def _wire(self):
        b = self._b
        for name in (
            'tab_changed', 'sig_load_audio', 'sig_edit_patterns',
            'sig_save_session', 'sig_save_session_as', 'sig_load_session',
            'sig_apply_hpf', 'sig_corr_recalc', 'sig_align_takes',
            'sig_align_preview', 'sig_align_ref', 'sig_open_calibracion',
            'sig_plot_params', 'sig_detect_notes', 'sig_edit_scale', 'sig_preset_changed',
            'sig_save_mask', 'sig_load_mask',
            'sig_export_all_images', 'sig_dir_display_changed', 'sig_intersect_cut3d', 'sig_theme_toggled',
        ):
            src = 'sig_tab_changed' if name == 'tab_changed' else name
            getattr(b, src).connect(getattr(self, name))

    # ── Fábricas de widgets (todas leen/escriben Bridge.state) ────────────
    def _sync(self):
        for load in self._loaders:
            load()

    def _num(self, key, width, tip, cb=None, nullable=False, placeholder=''):
        e = QLineEdit()
        e.setFixedWidth(width)
        e.setToolTip(tip)
        e.setPlaceholderText(placeholder)
        v = QDoubleValidator(e)
        v.setLocale(QLocale(QLocale.Language.C))
        v.setNotation(QDoubleValidator.Notation.StandardNotation)
        e.setValidator(v)

        def load():
            val = self._b.state.get(key)
            e.setText('' if val is None else '%g' % val)

        def commit():
            t = e.text().strip()
            try:
                if t:
                    self._b.state[key] = float(t)
                elif nullable:
                    self._b.state[key] = None
                else:
                    return load()
            except ValueError:
                return load()
            if cb:
                cb()

        e.editingFinished.connect(commit)
        self._loaders.append(load)
        load()
        return e

    def _combo(self, key, width, tip, items=(), cb=None, enc=None, dec=None):
        """items: [(label, data)]. state[key] = dec(data); al revés, enc(state[key]) = data."""
        enc = enc or (lambda v: v)
        dec = dec or (lambda d: d)
        c = QComboBox()
        c.setFixedWidth(width)
        c.setToolTip(tip)
        for label, data in items:
            c.addItem(label, data)

        def load():
            i = c.findData(enc(self._b.state.get(key)))
            if i >= 0:
                c.blockSignals(True)
                c.setCurrentIndex(i)
                c.blockSignals(False)

        def changed(_=None):
            self._b.state[key] = dec(c.currentData())
            if cb:
                cb()

        c.currentIndexChanged.connect(changed)
        c._load = load
        self._loaders.append(load)
        load()
        return c

    def _fill(self, c: QComboBox, items, key=None):
        """Repuebla un combo sin disparar señales y restaura la selección desde state."""
        c.blockSignals(True)
        c.clear()
        for label, data in items:
            c.addItem(label, data)
        c.blockSignals(False)
        if c.count():
            c._load()
            if key and c.currentData() is not None:
                # Si el valor guardado ya no existe, state pasa a lo que muestra el combo.
                self._b.state[key] = c.currentData() if key not in _INT_KEYS else int(c.currentData())

    def _button(self, text, tip, fn, name=None, primary=False, enabled=True, min_width=92):
        b = QPushButton(text)
        if min_width:
            b.setMinimumWidth(min_width)   # tamaño mínimo uniforme (texto corto no se ve "achicado" al lado de otros)
        b.setFixedHeight(22)    # misma altura que los combos/_tool() — Qt los calcula distinto si no
        b.setToolTip(tip)
        if primary:
            b.setObjectName("btn_primary")
        b.setEnabled(enabled)
        b.clicked.connect(lambda _=False: fn())
        if name:
            self._btn[name] = b
        return b

    @staticmethod
    def _green(btn):
        """Botón verde de acción principal."""
        btn.setStyleSheet("QPushButton { background:#2e7d32; color:white; font-weight:bold; padding:4px 10px; }"
                          "QPushButton:disabled { background:#9e9e9e; }")
        return btn

    def _row2(self, *pairs, expand_last: bool = False) -> QWidget:
        """Varios (label_o_None, widget) en una sola fila horizontal, para no gastar una fila
        de QFormLayout por campo cuando entran varios controles angostos juntos.
        `expand_last=True`: el último widget (p. ej. un botón "Aplicar") ocupa todo el resto
        del ancho en vez de dejarlo en blanco con un stretch."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        last = pairs[-1][1] if pairs else None
        for label, widget in pairs:
            if label:
                h.addWidget(QLabel(label))
            if expand_last and widget is last:
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                h.addWidget(widget, 1)
            else:
                h.addWidget(widget)
        if not expand_last:
            h.addStretch(1)
        return w

    def _grid_row(self, label, widget) -> QWidget:
        """Una fila: etiqueta + control angosto."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(label))
        h.addWidget(widget)
        h.addStretch(1)
        return w

    def _int_field(self, key, width, tip):
        """Campo de texto para un entero (sin flechitas); guarda en state[key] al confirmar."""
        from PyQt6.QtGui import QIntValidator
        le = QLineEdit(str(self._b.state.get(key, 0)))
        le.setFixedWidth(width)
        le.setToolTip(tip)
        le.setValidator(QIntValidator(0, 10, le))
        def done():
            self._b.state[key] = int(le.text() or 0)
        le.editingFinished.connect(done)
        return le

    def _corr_row(self, b) -> QWidget:
        """Nivelación: mic de referencia + toma base + 'Nivelar por toma' + 'Nivelar on axis',
        todo en una sola fila (tamaño de botón natural, igual que el resto — no se estira)."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(QLabel("Mic"))
        h.addWidget(self._combo('corr_ref', 80, "Micrófono de referencia que mide la emisión de cada toma (paso 2)",
                                [('ref', 'ref')] + [(str(t), str(t)) for t in range(0, 181, 10)]))
        h.addWidget(QLabel("Base"))
        h.addWidget(self._combo('corr_base', 80, "Giro (HOR) contra el que se compara cada toma. Por defecto 0°",
                                [(f'{a}°', str(a)) for a in range(0, 181, 10)]))
        h.addWidget(self._button("Nivelar por toma", "Recalcula sólo la corrección por toma con la referencia y toma base elegidas (matriz y dB vs tiempo)",
                                 lambda: b.corrRecalc()))
        h.addWidget(self._button("Nivelar on axis",
                                 "Paso 3: cada banda queda en 0 dB en la posición on-axis (giro 0°, θ 0°) sobre la grilla corregida.",
                                 lambda: b.nivelarOnaxis()))
        h.addStretch(1)
        return w

    def _tool(self, name, min_width=92) -> QToolButton:
        t = QToolButton()
        t.setDefaultAction(self._act[name])
        t.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        if min_width:
            t.setMinimumWidth(min_width)
        t.setFixedHeight(22)    # misma altura que _button()/los combos (Qt los calcula distinto si no)
        return t

    def _row(self, caption, items):
        h = QHBoxLayout()
        h.setSpacing(6)
        c = QLabel(caption)
        c.setObjectName("rb_cap")
        c.setFixedWidth(_CAP_W)
        h.addWidget(c)
        for it in items:
            h.addWidget(_vsep() if it == '|' else it if isinstance(it, QWidget) else QLabel(it))
        h.addStretch()
        return h

    def _page(self, rows):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 5, 8, 5)
        v.setSpacing(5)
        for cap, items in rows:
            v.addLayout(self._row(cap, items))
        return w

    # ── Acciones (menú + botones comparten estado habilitado) ─────────────
    def _make_actions(self):
        b = self._b

        def act(name, text, tip, fn, enabled=True):
            a = QAction(text, self)
            a.setToolTip(tip)
            a.setEnabled(enabled)
            a.triggered.connect(lambda _=False: fn())
            self._act[name] = a

        act('load_audio',  "Cargar audio…",   "Carga una carpeta de audios WAV y construye el tensor de medición", b.loadAudio)
        act('patterns',    "Patrones de archivos…", "Cómo se llaman los archivos de audio ({MIC} = micrófono, {H} = azimut)", b.editPatterns)
        self._make_view_actions()
        act('load_session', "Cargar",  "Abre una sesión (.cclp) guardada: los gráficos ya calculados y toda la interfaz, sin necesidad de los audios", b.loadSession)
        act('save_session', "Guardar", "Guarda en el mismo archivo .cclp cargado o guardado antes; si todavía no hay ninguno, pregunta dónde (como 'Guardar como…')", b.saveSession, False)
        act('save_grid', "Guardar grilla…", "Guarda la grilla procesada de 10° (corregida y nivelada, sin interpolar ni suavizar) en un .gcclp", b.saveGrid)
        act('load_grid', "Abrir grilla…", "Abre una grilla procesada guardada (.gcclp) y la muestra en la matriz y los gráficos", b.loadGrid)
        act('save_session_as', "Guardar como…", "Guarda los gráficos ya calculados (global y por nota) y toda la interfaz, sin los audios, eligiendo el archivo .cclp", b.saveSessionAs, False)
        # "Cargar/Guardar directividad (.npz)…" se sacó del menú: la sesión .cclp ya cubre el mismo caso
        # (mismo contenido, sin audio) y guarda además toda la interfaz, no sólo Directividad.
        act('calibrar',    "Calibración…",    "Abre la calibración: al aplicarla, el tensor pasa a dB SPL automáticamente", b.openCalibracion, False)
        act('save_mask',   "Guardar máscara…", "Guarda la segmentación de notas detectadas", b.saveMask, False)
        act('load_mask',   "Cargar máscara…", "Carga una segmentación de notas guardada", b.loadMask)
        act('export_all',  "Imágenes de directividad…", "Exporta las imágenes de los gráficos que elijas, para todas las bandas del rango", b.exportAllImages, False)
        act('edit_scale',  "Editar escala…",  "Crear o modificar una escala musical", b.editScale)
        act('seg_notas',   "Segmentación por notas…", "Alinear, elegir escala, detectar y extraer las notas de cada toma",
            lambda: self.sig_open_options.emit('notas'))
        act('smoothing',   "Suavizado…",      "Suavizado e interpolación — se aplica por igual a Polar 2D, Superficie 3D y Esfera",
            lambda: self.sig_open_options.emit('smoothing'))

    def _make_view_actions(self):
        """Menú Ver: Vista (Amplitud / Envolvente / dB, excluyentes) y Suavizado… (modal). Estado en Bridge.state."""
        b, plot = self._b, self._b.emitPlotParams

        group = QActionGroup(self)          # exclusivas: siempre hay un modo elegido

        def mode(name, text, tip, env, db, matrix=False):
            a = QAction(text, self)
            a.setCheckable(True)
            a.setToolTip(tip)
            group.addAction(a)
            a.triggered.connect(lambda _=False: (b.state.update(envelope=env, db=db, matrix=matrix), plot()))
            self._act[name] = a

        mode('amp', "Amplitud", "Señal en amplitud lineal", False, False)
        mode('envelope', "Envolvente", "Envolvente de la señal (transformada de Hilbert), amplitud lineal", True, False)
        mode('db', "dB", "Envolvente en escala logarítmica (dB)", True, True)
        mode('matrix', "Matriz radial", "Mallado radial de las mediciones (en lugar de la señal)", False, False, True)

        def load_mode():
            st = b.state
            self._act['matrix' if st.get('matrix') else 'db' if st.get('db') else 'envelope' if st.get('envelope') else 'amp'].setChecked(True)

        self._loaders.append(load_mode)
        load_mode()

        info = QAction("Información gráficos", self)
        info.setCheckable(True)
        info.setToolTip("Banda, máximo y dinámica sobre cada gráfico de Directividad")

        def load_info():
            info.blockSignals(True)
            info.setChecked(bool(b.state.get('show_info', False)))
            info.blockSignals(False)

        info.toggled.connect(lambda on: (b.state.update(show_info=on), b.dirDisplayChanged()))
        self._loaders.append(load_info)
        load_info()
        self._act['info'] = info

        sm = QAction(self)
        sm.setToolTip("Suavizado de la envolvente (media móvil, en ms). Mayor valor = curva más suave")

        def load_smooth():
            sm.setText("Suavizado…")

        def ask_smooth():
            text, ok = QInputDialog.getText(
                self.window(), "Suavizado",
                "Método: promedio móvil (ventana rectangular) sobre la envolvente de Hilbert.\n"
                "Ancho de la ventana (ms); 0 = sin suavizado:",
                text=f"{b.state.get('smooth', 20.0):g}")
            if not ok:
                return
            try:
                v = float(text.strip().replace(',', '.'))
            except ValueError:
                return
            if v >= 0:
                b.state['smooth'] = v
                load_smooth()
                plot()

        sm.triggered.connect(lambda _=False: ask_smooth())
        self._loaders.append(load_smooth)
        load_smooth()
        self._act['smooth'] = sm

    def _set_palette(self, name: str):
        self._b.state['colorscale'] = name
        self._b.dirDisplayChanged()

    def _sync_palette_menu(self):
        cur = self._b.state.get('colorscale', 'RdBu v4')
        for name, a in self._palette_actions.items():
            a.setChecked(name == cur)

    def _make_menubar(self) -> QMenuBar:
        mb = QMenuBar()
        m = mb.addMenu("&Archivo")
        for n in ('load_audio', 'patterns'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('load_session', 'save_session', 'save_session_as'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('save_grid', 'load_grid'):
            m.addAction(self._act[n])
        m.addSeparator()
        m.addMenu("Exportar").addAction(self._act['export_all'])
        m.addSeparator()
        m.addAction("Salir", lambda: self.window().close())

        m = self._menu_ver = mb.addMenu("&Ver")
        self._ver_vista = QMenu("Vista", self)          # Amplitud / Envolvente / dB (Procesamiento)
        for n in ('amp', 'envelope', 'db'):
            self._ver_vista.addAction(self._act[n])
        self._ver_extra = []                             # paneles (los agrega MainWindow)
        self._act_dark = QAction("Tema oscuro", self)
        self._act_dark.setCheckable(True)
        self._act_dark.setChecked(_theme.is_dark())
        self._act_dark.triggered.connect(lambda _=False: self.sig_theme_toggled.emit())

        m = mb.addMenu("&Herramientas")
        for n in ('seg_notas', 'save_mask', 'load_mask'):
            m.addAction(self._act[n])

        m = mb.addMenu("&Opciones")
        g = m.addMenu("Gráficos")
        for key, text in (("polar2d", "Polar 2D…"), ("spectrum", "Espectro…"), ("sphere", "Esfera 3D…"),
                          ("3d", "Superficie 3D…"), ("images", "Imágenes…")):
            if key == "images":
                g.addSeparator()
            a = g.addAction(text)
            a.triggered.connect(lambda _=False, k=key: self.sig_open_options.emit(k))
            a.setToolTip("Tamaño, DPI y formato de las imágenes exportadas" if key == "images"
                         else "Todas las opciones de este gráfico (escala, ejes, líneas, estilos…)")
        g.addSeparator()
        pal = g.addMenu("Paleta de colores (3D y Esfera)")
        pal_group = QActionGroup(self)          # exclusivas: siempre hay una paleta elegida
        self._palette_actions = {}
        for name in PALETTES:
            a = pal.addAction(name)
            a.setCheckable(True)
            a.setActionGroup(pal_group)
            a.triggered.connect(lambda _=False, n=name: self._set_palette(n))
            self._palette_actions[name] = a
        pal.aboutToShow.connect(self._sync_palette_menu)

        m = mb.addMenu("A&yuda")
        m.addAction("Acerca de…", self._about)
        return mb

    def add_view_action(self, action: QAction):
        """MainWindow agrega acá p. ej. el mostrar/ocultar del panel de parámetros."""
        self._ver_extra.append(action)
        self._rebuild_ver(self._tabs.currentIndex())

    def _rebuild_ver(self, tab: int):
        """El menú Ver cambia según la pestaña: Procesamiento (vista de la señal) o Directividad."""
        m = self._menu_ver
        m.clear()
        if tab != 0:
            m.addAction(self._act['info'])
            m.addSeparator()
        for a in self._ver_extra:
            m.addAction(a)

    def _about(self):
        from version import __version__, APP_NAME
        QMessageBox.about(
            self.window(), "Acerca de",
            f"<b>{APP_NAME}</b> &nbsp;v{__version__}<br><br>"
            "GUI realizada para mediciones de patrón polar.<br><br>"
            "Dudas, bugs o recomendaciones: "
            "<a href=\"mailto:abellamasm@gmail.com\">abellamasm@gmail.com</a>")

    def _make_tabbar(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(6, 0, 8, 0)
        self._tabs = QTabBar()
        self._tabs.setObjectName("main_tabs")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(False)
        for i, (name, tip) in enumerate(_TABS):
            self._tabs.addTab(name)
            self._tabs.setTabToolTip(i, tip)
        self._tabs.currentChanged.connect(self._on_tab)
        h.addWidget(self._tabs)
        h.addStretch()
        self._chip = QLabel()
        self._chip.setObjectName("rb_chip")
        self._chip.setToolTip("Estado del tensor cargado en memoria")
        h.addWidget(self._chip)
        self._set_chip("Sin datos", False)
        return h

    def _set_chip(self, text: str, ok: bool):
        color = _theme.current()['ok'] if ok else '#c0392b'
        self._chip.setText(f'<span style="color:{color}">●</span>&nbsp;{text}')

    def _on_tab(self, i: int):
        self._rebuild_ver(i)
        self._b.tabClicked(i)

    # ── Paneles laterales (grupos por lo que se edita) ────────────────────
    def _flex(self, w: QWidget) -> QWidget:
        """Los controles de un panel se estiran al ancho disponible (las fábricas fijan un ancho de barra)."""
        w.setMinimumWidth(0)
        w.setMaximumWidth(16777215)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return w

    def _row(self, *widgets: QWidget) -> QWidget:
        """Varios widgets uno al lado del otro, sin nada entre medio (a diferencia de _pair)."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for wid in widgets:
            h.addWidget(wid)
        h.addStretch(1)
        return w

    def _pair(self, a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(self._flex(a))
        h.addWidget(QLabel("–"))
        h.addWidget(self._flex(b))
        return w

    def _with_info(self, field: QWidget, title: str, html: str) -> QWidget:
        """Campo + botón (i) que abre un modal explicativo."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(self._flex(field))
        b = QToolButton()
        b.setText("i")
        b.setObjectName("rb_info")
        b.setToolTip("Qué es y cómo se usa")
        b.setFixedSize(22, 22)
        b.clicked.connect(lambda _=False: QMessageBox.information(self.window(), title, html))
        h.addWidget(b)
        return w

    def _group(self, title: str, rows) -> QGroupBox:
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setContentsMargins(8, 4, 8, 8)
        f.setSpacing(5)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for label, w in rows:
            self._flex(w)
            f.addRow(label, w) if label else f.addRow(w)
        return g

    def _panel(self, groups) -> QScrollArea:
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(4)
        for title, rows in groups:
            # título None + un widget ya armado (en vez de filas): se agrega directo, sin QGroupBox alrededor
            v.addWidget(rows if title is None else self._group(title, rows))
        v.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setMinimumWidth(250)
        sc.setWidget(inner)
        return sc

    def _panel_proc(self):
        b = self._b
        plot = b.emitPlotParams
        disp = b.dirDisplayChanged
        th = dict(enc=lambda v: str(v), dec=lambda d: d)
        self._c_theta    = self._combo('theta', 78, "Elevación (micrófono) a visualizar", cb=plot, **th)
        self._c_az       = self._combo('az', 78, "Azimuth a visualizar, o 'Todos' para superponer las tomas", cb=plot, **th)
        self._c_nota_proc = self._combo('nota', 190,
            "Sobre qué se procesa y grafica: toda la toma, o una nota segmentada. Elegís libremente, no fuerza nada más.",
            [("Todo el audio", "Todo el audio")], disp)
        return self._panel([
            ("Señal", [
                (None, self._row2(
                    ("Elev. (θ Mic)", self._c_theta),
                    ("Azimut", self._c_az)))]),
            ("Filtro y calibración", [
                (None, self._row2(
                    ("HPF (Hz)", self._num('hpf_hz', 52, "Frecuencia de corte del pasa-altos (Hz)")),
                    (None, self._button("Aplicar HPF", "Aplica el Butterworth pasa-altos al tensor (irreversible en memoria)",
                                        lambda: b.applyHpf(), 'hpf', enabled=False)),
                    (None, self._tool('calibrar'))))]),
            ("Procesar", [
                (None, self._row2(
                    ("Nota", self._c_nota_proc),
                    (None, self._button("Filtrar 1/3 oct", "Calcula el Leq de cada grabación en bandas de 1/3 de octava (paso 1). Lo usa Nivelar por toma.",
                                        lambda: b.filterBands()))))]),
            ("Nivelación", [
                (None, self._corr_row(b)),
            ]),
            ("Interpolación", [
                (None, self._row2(
                    ("Método", self._combo('interp_method', 130,
                        "Estima valores entre las mediciones de 10°. Lineal: rectas. Bicúbica: curva suave.",
                        [('lineal', 'lineal'), ('bicúbica', 'bicúbica')])),
                    ("Paso", self._combo('interp_step', 120,
                        "Paso de la grilla interpolada: ninguna (medida, 10°), 5° o 2°.",
                        [('ninguna', 0), ('5°', 5), ('2°', 2)])),
                    (None, self._button("Aplicar", "Aplica la interpolación elegida a la matriz",
                                        lambda: b.matrixGridChanged(), min_width=0)))),
            ]),
            ("Suavizado", [
                (None, self._row2(
                    ("Método", self._combo('smooth_method', 166,
                        "Cambia los valores medidos para quitar ruido. Gaussiano es el más seguro.",
                        [('ninguno', 'ninguno'), ('gaussiano', 'gaussiano'), ('savgol', 'savgol'), ('media móvil', 'media móvil')])),
                    ("Int.", self._int_field('smooth_int', 60,
                        "0 = sin suavizar. 1 a 2 = leve. 3 a 5 = fuerte.")),
                    (None, self._button("Aplicar", "Aplica el suavizado elegido a la matriz",
                                        lambda: b.matrixGridChanged(), min_width=0)))),
            ]),
        ])

    # ── Alineaciones: controles en el panel de Procesamiento (antes, diálogos en Herramientas) ─
    def _make_align_dialogs(self):
        th = dict(enc=lambda v: str(v), dec=lambda d: d)
        self._c_align_th = self._combo('align_theta', 80, "Micrófono de referencia para la alineación",
                                       cb=self._b.emitAlignPreview, **th)

    # ── Panel de trabajo de notas: todo el flujo (alinear, escala, detectar) en la vista Notas,
    # no en Procesamiento — TabNotas lo embebe arriba de la tabla/editor F0.
    def build_notas_panel(self) -> QScrollArea:
        b = self._b
        th = dict(enc=lambda v: str(v), dec=lambda d: d)
        self._c_preset = QComboBox()
        self._c_preset.setFixedWidth(150)
        # QComboBox.minimumSizeHint() ignora el setFixedWidth de arriba y mide según el ítem
        # más largo de la lista (nombres de escala, sin tope) — eso infla el ancho mínimo que
        # layouts padre (QFormLayout/QGridLayout) le exigen a todo el grupo. Lo acotamos a mano.
        self._c_preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._c_preset.setMinimumContentsLength(8)
        self._c_preset.setToolTip("Escala musical de referencia para detectar notas")
        from ui.scale_dialog import fill_scale_combo
        self._fill_scales = fill_scale_combo
        fill_scale_combo(self._c_preset, "Fa mayor")
        self._c_preset.currentIndexChanged.connect(
            lambda _i: b.presetChanged(self._c_preset.currentData()) if self._c_preset.currentData() else None)
        self._c_note_th = self._combo('note_theta', 80, "Micrófono usado para detectar notas", **th)

        g_tomas = self._group("Alinear entre tomas", [
            (None, self._row2(
                ("Onset", self._num('onset', 36, "Tiempo objetivo del onset tras alinear (s)", b.emitAlignPreview)),
                ("Umbral", self._num('thresh', 36, "Nivel mínimo para detectar el onset (dBFS)", b.emitAlignPreview)))),
            (None, self._button("Alinear", "Alinea las tomas por onset según el umbral",
                                lambda: b.alignTakes(), 'align_takes', enabled=False, min_width=0))])
        g_mics = self._group("Alinear entre micrófonos", [
            (None, self._row2(
                ("Vent.", self._num('window_ms', 32, "Ventana de análisis GCC-PHAT (ms)")),
                ("Mic", self._c_align_th),
                ("Umbral", self._num('gcc_thresh', 36, "Umbral GCC: nivel mínimo de la toma para GCC-PHAT. Vacío = sin filtro",
                                     nullable=True, placeholder="—")))),
            (None, self._button("Alinear", "Alinea los micrófonos al de referencia con GCC-PHAT",
                                lambda: b.alignRef(), 'align_ref', enabled=False, min_width=0))])
        edit_scale_btn = self._tool('edit_scale', min_width=0)
        edit_scale_btn.setText("Editar")
        g_scale = self._group("Escala musical", [
            (None, self._c_preset),
            (None, edit_scale_btn)])

        # Detectar notas: todos los parámetros + el botón en una sola fila, usando todo el ancho
        # disponible (la fila de arriba ya ocupa las 3 columnas, así que acá entra holgado).
        g_detect = self._group("Detectar notas", [
            (None, self._row2(
                ("Toler.", self._num('note_tol', 38, "Cuánto puede desafinar un frame de la nota de la escala y seguir contando como esa nota, en cents "
                    "(100 ¢ = 1 semitono). Valores típicos: 30–50 ¢. Más alto → acepta frames más desafinados (segmentos más largos pero menos precisos); "
                    "más bajo → más estricto (puede partir una nota sostenida en varios segmentos si el cantante desafina un poco).")),
                ("Pureza", self._num('note_purity', 38, "Fracción de frames del tramo que deben caer dentro de la tolerancia para aceptarlo como esa nota (0 a 1; "
                    "0.8 = 80%). Valores típicos: 0.7–0.9. Más alto → sólo acepta tramos bien afinados y estables (descarta ataques/deslizamientos, puede "
                    "perder notas cortas); más bajo → acepta tramos más sucios o con glissando (riesgo de falsos positivos).")),
                ("Inicio", self._num('note_start', 38, "Segundos que se ignoran al principio de la toma antes de buscar notas (para saltar silencio o el "
                    "ataque inicial del cantante, que suele desafinar). 0 = analiza desde el primer frame.")),
                ("Grad.", self._num('note_grad', 38, "Cuánto puede variar el pitch entre frames consecutivos (¢ por frame) para seguir considerándose la "
                    "misma nota sostenida, en vez de un vibrato/glissando que corta el segmento. Valores típicos: 20–30 ¢/frame. Más alto → tolera más "
                    "vibrato sin cortar la nota; más bajo → corta el segmento ante el mínimo movimiento de pitch.")),
                ("Mic", self._c_note_th),
                (None, self._button("Detectar", "Detecta y segmenta automáticamente las notas",
                                    lambda: b.detectNotes(), 'detect', enabled=False, min_width=0)),
                (None, self._tool('save_mask', min_width=0)),
                (None, self._tool('load_mask', min_width=0))))])

        # Fila 1: las 3 cajas chicas una al lado de la otra. Fila 2: Detectar notas, ancho completo.
        for g in (g_tomas, g_mics, g_scale, g_detect):
            g.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(6, 4, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.addWidget(g_tomas,  0, 0)
        grid.addWidget(g_mics,   0, 1)
        grid.addWidget(g_scale,  0, 2)
        grid.addWidget(g_detect, 1, 0, 1, 3)
        grid.setRowStretch(2, 1)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        # A diferencia del dock de Parámetros (angosto, scroll horizontal prohibido), esta vista
        # vive en el área central: casi siempre entra entero, pero si la ventana se achica mucho
        # un scroll horizontal es preferible a recortar contenido sin forma de verlo.
        sc.setWidget(inner)
        return sc

    # ── Ventana de Notas (filas horizontales) ─────────────────────────────
    def _panel_dir(self):
        b = self._b
        disp = b.dirDisplayChanged
        as_int = dict(enc=lambda v: str(int(float(v))) if v is not None else None,
                      dec=lambda d: int(float(d)) if d is not None else 0)

        self._c_el = self._combo('el_idx', 140, "Elevación del corte polar 2D (sólo plano XY)",
                                 [("Auto (0°)", 0)], disp,
                                 enc=lambda v: 0 if v is None else v + 1,
                                 dec=lambda d: None if d == 0 else d - 1)

        def on_plane(_=None):
            self._c_el.setEnabled(b.state.get('polar_plane', 'XY') == 'XY')
            disp()

        self._c_plane = self._combo('polar_plane', 150, "Plano del corte polar 2D",
                                    [("XY (horiz.)", "XY"), ("XZ (0°/180°)", "XZ"),
                                     ("YZ (90°/270°)", "YZ")], on_plane)
        self._dir_status = QLabel("Sin datos.")
        self._dir_status.setObjectName("rb_status")
        self._dir_status.setWordWrap(True)
        return self._panel([
            ("Cálculo", [
                ("Rango (Hz)", self._pair(self._num('hz_min', 52, "Frecuencia mínima a mostrar (Hz)", disp),
                                          self._num('hz_max', 56, "Frecuencia máxima a mostrar (Hz)", disp))),
                (None, self._dir_status)]),
            ("Polar 2D", [
                (None, self._row2(
                    ("Plano", self._c_plane),
                    ("Elev.", self._c_el))),
                ("Simet.", self._combo('symmetry', 140, "Simetría: espeja los datos medidos para completar el patrón",
                                       [("Ninguna", "none"), ("XZ (izq↔der)", "azimuth"),
                                        ("XY (sup↔inf)", "elevation"), ("XZ + XY", "both")], disp))]),
            ("Corte (Superficie 3D)", [
                (None, self._row2(
                    ("Elevación (°)", self._num('cut3d_elevation', 52,
                        "Elevación del plano/curva de referencia (0° a 90°)")),
                    (None, self._button("Intersectar", "Muestra el plano de referencia y la curva real a esta "
                        "elevación sobre la Superficie 3D — no afecta a Polar 2D, es independiente.",
                        lambda: b.intersectCut3D()))))]),
            ("Espectro", [
                (None, self._row2(
                    ("Audio", self._with_info(
                        self._combo('spec_data', 120, "Señales originales, o igualadas en nivel para comparar la forma espectral",
                                    [("Originales", 0), ("Igualados", 1)], disp),
                        "Espectro: Originales / Igualados en nivel", '<b>Originales</b><br>Espectro del micrófono de referencia en cada toma, tal como se midió. Incluye las diferencias de nivel con que el cantante emitió en cada toma.<br><br><b>Igualados en nivel</b><br>Espectro después de la corrección de emisión que usa el cálculo de directividad: se compensa, banda por banda, la diferencia de nivel de cada toma respecto de la toma de referencia (Ref. azimut). Así todas las tomas quedan al mismo nivel y solo importa la forma del espectro, no cuánto cantó más fuerte o más suave en cada toma.<br><br>Como la corrección se calcula con ese mismo micrófono, en <i>Igualados</i> todas las tomas coinciden; la vista Por toma sirve sobre todo con <i>Originales</i>.')),
                    ("Curvas", self._combo('spec_global', 128, "Global: promedio de todos los ángulos. Por toma: una curva por azimuth",
                                           [("Global", True), ("Por toma", False)], disp))))]),
        ])

    # ── API pública idéntica a HtmlRibbon ─────────────────────────────────
    def _switch_tab(self, idx: int):
        self._tabs.setCurrentIndex(idx)

    def _update_theme_icon(self, palette: dict):
        self._act_dark.setChecked(palette.get('name') == 'dark')
        self._set_chip_from_last()

    def _set_chip_from_last(self):
        if getattr(self, '_chip_last', None):
            self._set_chip(*self._chip_last)

    def set_ma_loaded(self, ma):
        thetas = list(ma.thetas)
        angles = list(ma.angles)
        tl = lambda t: 'ref' if t == 'ref' else f'{_num_str(t)}°'
        tv = lambda t: 'ref' if t == 'ref' else _num_str(t)
        th_items = [(tl(t), tv(t)) for t in thetas]
        az_items = [(f'{_num_str(a)}°', _num_str(a)) for a in angles]
        self._fill(self._c_theta, [("Todos", "Todos")] + th_items, 'theta')
        self._fill(self._c_align_th, th_items, 'align_theta')
        self._fill(self._c_note_th, th_items, 'note_theta')
        self._fill(self._c_az, [("Todos", "Todos")] + az_items, 'az')

        is_spl = bool(getattr(ma, '_is_spl', False))
        for n in ('hpf', 'align_takes', 'align_ref', 'detect'):
            self._btn[n].setEnabled(True)
        self._act['calibrar'].setEnabled(True)

        sr = getattr(ma, 'sr', 0) // 1000
        self._chip_last = (f"{len(angles)} × {len(thetas)} · {sr} kHz" + (' · SPL ✓' if is_spl else ''), True)
        self._set_chip(*self._chip_last)
        self._sync()                 # numéricos/checks/pills desde state (p. ej. sesión cargada)
        self._b.emitPlotParams()
        self._b.emitAlignPreview()

    def current_scale_name(self):
        return self._c_preset.currentData()

    def refresh_scales(self, select: str | None = None):
        """Vuelve a llenar el combo (después de editar la base propia) y elige `select`, avisando el cambio."""
        self._fill_scales(self._c_preset, select or self._c_preset.currentData())
        if self._c_preset.currentData():
            self._b.presetChanged(self._c_preset.currentData())

    def apply_ui_state(self, d: dict):
        """Vuelca valores guardados (p. ej. de un .npz de directividad) a Bridge.state y a los controles."""
        self._b.state.update(d)
        self._sync()

    def set_notes_loaded(self, notes: list):
        items = [("Todo el audio", "Todo el audio")] + [(n, n) for n in notes]
        self._fill(self._c_nota_proc, items, 'nota')

    def set_dir_computed(self, thetas):
        self._fill(self._c_el, [("Auto (0°)", 0)] + [(f'{round(float(t))}°', i + 1) for i, t in enumerate(thetas)])
        self._c_el.setCurrentIndex(0)
        self._b.state['el_idx'] = None
        for n in ('save_session', 'save_session_as', 'export_all'):
            self._act[n].setEnabled(True)

    def set_dir_status(self, text: str):
        self._dir_status.setText(text.replace('\n', ' · '))

    def get_dir_display_params(self) -> dict:
        s = self._b.state
        return dict(
            hz_min      = float(s.get('hz_min', 315.0)),
            hz_max      = float(s.get('hz_max', 10000.0)),
            colorscale  = str(s.get('colorscale', 'RdBu v4')),
            el_index    = s.get('el_idx'),
            plane       = str(s.get('polar_plane', 'XY')),
            show_info   = bool(s.get('show_info', False)),
            symmetry    = str(s.get('symmetry', 'none')),
            nota        = str(s.get('nota', 'Todo el audio')),
            spec_data   = int(s.get('spec_data', 0)),
            spec_global = bool(s.get('spec_global', True)),
            view_checks = {'3d': True, 'sphere': True, 'polar2d': True, 'spectrum': True},
        )


_INT_KEYS = ('ref_az', 'ref_th')
