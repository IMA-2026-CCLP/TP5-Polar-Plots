"""
ui/native_ribbon.py — Barra superior nativa estilo VituixCAD: menú + pestañas + filas de parámetros.

Reemplaza a HtmlRibbon (shell.html + QWebChannel) con widgets Qt normales, pero
conserva exactamente su API pública (señales, proxies, métodos) para que
MainWindow no cambie. `Bridge` se sigue usando como contenedor de `state` y de
los slots que arman los parámetros de cada señal (`emitPlotParams`, `computeDir`…);
ahora los llaman los widgets directamente en vez de JS.

Los valores por defecto de los controles salen de `Bridge.state`: no se repiten acá.
"""
import json

from PyQt6.QtCore import Qt, QLocale, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QDoubleValidator
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QGroupBox, QInputDialog, QMenu, QMessageBox, QScrollArea, QSizePolicy, QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QTabBar, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QFrame, QToolButton,
)

from ui.bridge import Bridge
from ui import theme as _theme

_TABS = [
    ("Procesamiento", "Visualizar señales, aplicar filtros y alinear tomas"),
    ("Directividad",  "Calcular y visualizar el patrón de directividad acústica"),
]
_GCC_HELP = '<b>¿Para qué sirve?</b><br>Al alinear los micrófonos se estima el retardo entre cada uno y el de referencia con GCC-PHAT (correlación cruzada). Este umbral pone en cero, antes de correlacionar, los tramos de la señal de referencia que están por debajo de ese nivel, para que el ruido de fondo y el silencio no falseen la estimación.<br><br><b>¿Cómo se usa?</b><br>&bull; <b>Vacío</b>: no filtra nada (valor por defecto).<br>&bull; <b>Con valor</b> (dBFS): ponelo un poco por encima del ruido de fondo, por ejemplo entre &minus;55 y &minus;40 dBFS, cerca del umbral que usaste para el onset.<br>&bull; Si es demasiado alto se descartan partes útiles del canto y la alineación empeora.<br><br>Sólo afecta a <i>Alinear micrófonos</i>. <i>Alinear tomas</i> usa el Umbral del onset.'
_CAP_W = 78   # ancho de la columna de títulos de fila (Cálculo, Vista…)


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
    sig_open_notas      = pyqtSignal()
    sig_open_options    = pyqtSignal(str)     # 'polar2d' | 'spectrum' | 'sphere' | '3d' | 'images'
    sig_save_tensor     = pyqtSignal()
    sig_load_tensor     = pyqtSignal()
    sig_save_session    = pyqtSignal()
    sig_load_session    = pyqtSignal()
    sig_load_polar_npz  = pyqtSignal()
    sig_save_polar_npz  = pyqtSignal()

    sig_apply_hpf        = pyqtSignal(float)
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

    sig_compute_dir         = pyqtSignal(str, float, float, int, int)
    sig_save_dir_npz        = pyqtSignal()
    sig_export_all_images   = pyqtSignal()
    sig_dir_display_changed = pyqtSignal()

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
        self.proc_panel = self._panel_proc()
        self.dir_panel  = self._panel_dir()
        self.notas_page = self._page_notas()
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
            'tab_changed', 'sig_load_audio', 'sig_edit_patterns', 'sig_save_tensor', 'sig_load_tensor',
            'sig_save_session', 'sig_load_session',
            'sig_load_polar_npz', 'sig_save_polar_npz', 'sig_apply_hpf', 'sig_align_takes',
            'sig_align_preview', 'sig_align_ref', 'sig_open_calibracion',
            'sig_plot_params', 'sig_detect_notes', 'sig_edit_scale', 'sig_preset_changed',
            'sig_save_mask', 'sig_load_mask', 'sig_compute_dir', 'sig_save_dir_npz',
            'sig_export_all_images', 'sig_dir_display_changed', 'sig_theme_toggled',
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

    def _button(self, text, tip, fn, name=None, primary=False, enabled=True):
        b = QPushButton(text)
        b.setToolTip(tip)
        if primary:
            b.setObjectName("btn_primary")
        b.setEnabled(enabled)
        b.clicked.connect(lambda _=False: fn())
        if name:
            self._btn[name] = b
        return b

    def _tool(self, name) -> QToolButton:
        t = QToolButton()
        t.setDefaultAction(self._act[name])
        t.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
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
        act('notas',       "Detección de notas…", "Abre la ventana para detectar, editar y extraer las notas", self.sig_open_notas.emit)
        act('load_session', "Cargar sesión (.cclp)…",  "Abre una sesión guardada: los gráficos ya calculados y toda la interfaz, sin necesidad de los audios", b.loadSession)
        act('save_session', "Guardar sesión (.cclp)…", "Guarda los gráficos ya calculados (global y por nota) y toda la interfaz, sin los audios", b.saveSession, False)
        act('load_tensor', "Cargar audio procesado (.npz)…",  "Carga un tensor de audio ya preprocesado, guardado antes con 'Guardar audio procesado'", b.loadTensor)
        act('save_tensor', "Guardar audio procesado (.npz)…", "Guarda el audio (con calibración) para resumir el preprocesamiento más tarde sin los WAV originales", b.saveTensor, False)
        act('load_polar',  "Cargar directividad (sin audios)…", "Abre un .npz de directividad: los gráficos y su configuración, sin necesidad de los audios", b.loadPolarNpz)
        act('save_polar',  "Guardar directividad (sin audios)…", "Guarda los resultados calculados y la configuración de los gráficos en un .npz (sin los audios)", b.savePolarNpz, False)
        act('align_takes', "Alinear entre tomas (onset)…", "Opcional: alinea el inicio de cada toma para superponerlas en la vista de Procesamiento", lambda: self._dlg_takes.exec(), False)
        act('align_mics',  "Alinear entre micrófonos (retardo)…", "Opcional: corrige el retardo de cada micrófono respecto al de referencia (GCC-PHAT)", lambda: self._dlg_mics.exec(), False)
        act('calibrar',    "Calibración…",    "Abre la calibración: al aplicarla, el tensor pasa a dB SPL automáticamente", b.openCalibracion, False)
        act('save_mask',   "Guardar máscara…", "Guarda la segmentación de notas detectadas", b.saveMask, False)
        act('load_mask',   "Cargar máscara…", "Carga una segmentación de notas guardada", b.loadMask)
        act('export_all',  "Imágenes de directividad…", "Exporta las imágenes de los gráficos que elijas, para todas las bandas del rango", b.exportAllImages, False)
        act('edit_scale',  "Editar escala…",  "Crear o modificar una escala musical", b.editScale)

    def _make_view_actions(self):
        """Menú Ver: Vista (Amplitud / Envolvente / dB, excluyentes) y Suavizado… (modal). Estado en Bridge.state."""
        b, plot = self._b, self._b.emitPlotParams

        group = QActionGroup(self)          # exclusivas: siempre hay un modo elegido

        def mode(name, text, tip, env, db):
            a = QAction(text, self)
            a.setCheckable(True)
            a.setToolTip(tip)
            group.addAction(a)
            a.triggered.connect(lambda _=False: (b.state.update(envelope=env, db=db), plot()))
            self._act[name] = a

        mode('amp', "Amplitud", "Señal en amplitud lineal", False, False)
        mode('envelope', "Envolvente", "Envolvente de la señal (transformada de Hilbert), amplitud lineal", True, False)
        mode('db', "dB", "Envolvente en escala logarítmica (dB)", True, True)

        def load_mode():
            st = b.state
            self._act['db' if st.get('db') else 'envelope' if st.get('envelope') else 'amp'].setChecked(True)

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

    def _make_menubar(self) -> QMenuBar:
        mb = QMenuBar()
        m = mb.addMenu("&Archivo")
        for n in ('load_audio', 'patterns', 'load_tensor', 'save_tensor'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('load_session', 'save_session', 'load_polar', 'save_polar'):
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
        for n in ('align_takes', 'align_mics'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('notas', 'edit_scale', 'save_mask', 'load_mask'):
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
        if tab == 0:
            m.addMenu(self._ver_vista)
            m.addAction(self._act['smooth'])
        else:
            m.addAction(self._act['info'])
        m.addSeparator()
        m.addAction(self._act_dark)
        m.addSeparator()
        for a in self._ver_extra:
            m.addAction(a)

    def _about(self):
        from version import __version__, APP_NAME
        QMessageBox.about(
            self.window(), "Acerca de",
            f"<b>{APP_NAME}</b> &nbsp;v{__version__}<br><br>"
            "Análisis y visualización de la directividad polar de la voz cantada, "
            "medida con un array semicircular de micrófonos.")

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
            v.addWidget(self._group(title, rows))
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
        th = dict(enc=lambda v: str(v), dec=lambda d: d)
        self._c_theta    = self._combo('theta', 78, "Elevación (micrófono) a visualizar", cb=plot, **th)
        self._c_az       = self._combo('az', 78, "Azimuth a visualizar, o 'Todos' para superponer las tomas", cb=plot, **th)
        return self._panel([
            ("Señal", [
                ("Elevación θ (Mic)", self._c_theta),
                ("Azimut (Toma)", self._c_az)]),
            ("Eje Y", [
                ("Mín – Máx", self._pair(
                    self._num('ymin', 50, "Límite inferior del eje Y. Vacío = autoescala", plot, True, "auto"),
                    self._num('ymax', 50, "Límite superior del eje Y. Vacío = autoescala", plot, True, "auto")))]),
            ("Filtro pasa-altos", [
                ("Frecuencia (Hz)", self._num('hpf_hz', 52, "Frecuencia de corte del pasa-altos (Hz)")),
                (None, self._button("Aplicar HPF", "Aplica el Butterworth pasa-altos al tensor (irreversible en memoria)",
                                    lambda: b.applyHpf(), 'hpf', enabled=False))]),
            ("Calibración", [
                (None, self._tool('calibrar'))]),
        ])

    # ── Alineaciones (opcionales): diálogos abiertos desde Herramientas ────
    def _align_dialog(self, title: str, rows) -> QDialog:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(380)
        v = QVBoxLayout(dlg)
        g = self._group("", rows)
        g.setObjectName("prop_page")
        v.addWidget(g)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(dlg.reject)
        row.addWidget(close)
        v.addLayout(row)
        return dlg

    def _make_align_dialogs(self):
        b = self._b
        prev = b.emitAlignPreview
        th = dict(enc=lambda v: str(v), dec=lambda d: d)
        self._c_align_th = self._combo('align_theta', 64, "Micrófono de referencia para la alineación", cb=prev, **th)
        self._dlg_takes = self._align_dialog("Alinear entre tomas (onset)", [
            ("Onset (s)", self._num('onset', 44, "Tiempo objetivo del onset tras alinear (s)", prev)),
            ("Umbral (dBFS)", self._num('thresh', 44, "Nivel mínimo para detectar el onset (dBFS)", prev)),
            (None, self._button("Alinear tomas", "Alinea las tomas por onset según el umbral",
                                lambda: b.alignTakes(), 'align_takes', primary=True, enabled=False))])
        self._dlg_mics = self._align_dialog("Alinear entre micrófonos (retardo)", [
            ("Ventana (ms)", self._num('window_ms', 40, "Ventana de análisis GCC-PHAT (ms)")),
            ("Mic ref", self._c_align_th),
            ("Umbral GCC (dBFS)", self._with_info(
                self._num('gcc_thresh', 48, "Nivel mínimo de la toma para GCC-PHAT. Vacío = sin filtro",
                          nullable=True, placeholder="sin filtro"),
                "Umbral GCC", _GCC_HELP)),
            (None, self._button("Alinear mics", "Alinea los micrófonos al de referencia con GCC-PHAT",
                                lambda: b.alignRef(), 'align_ref', primary=True, enabled=False))])
        # al aplicar, el diálogo se cierra (el progreso se ve en la barra de estado)
        self._btn['align_takes'].clicked.connect(self._dlg_takes.accept)
        self._btn['align_ref'].clicked.connect(self._dlg_mics.accept)

    # ── Ventana de Notas (filas horizontales) ─────────────────────────────
    def _page_notas(self):
        b = self._b
        self._c_preset = QComboBox()
        self._c_preset.setFixedWidth(170)
        self._c_preset.setToolTip("Escala musical de referencia para detectar notas")
        from ui.scale_dialog import fill_scale_combo
        self._fill_scales = fill_scale_combo
        fill_scale_combo(self._c_preset, "Fa mayor")
        self._c_preset.currentIndexChanged.connect(
            lambda _i: b.presetChanged(self._c_preset.currentData()) if self._c_preset.currentData() else None)

        self._c_note_th = self._combo('note_theta', 64, "Micrófono usado para detectar notas",
                                      enc=lambda v: str(v), dec=lambda d: d)
        n = lambda k, w, tip: self._num(k, w, tip)
        return self._page([
            ("Escala", [self._c_preset, self._tool('edit_scale'), '|',
                        self._tool('save_mask'), self._tool('load_mask')]),
            ("Detección", [
                "Tol ¢", n('note_tol', 40, "Tolerancia en cents para aceptar una frecuencia como nota (100 ¢ = 1 semitono)"),
                "Pureza", n('note_purity', 40, "Fracción mínima de frames asignados a la nota (0–1)"),
                "Inicio", n('note_start', 40, "Segundo desde el cual se analiza (omite el ataque)"),
                "Grad", n('note_grad', 40, "Gradiente máx. (¢/frame) para considerar estable el tono"),
                "Ref θ", self._c_note_th,
                self._button("♪ Detectar notas", "Detecta y segmenta automáticamente las notas",
                             lambda: b.detectNotes(), 'detect', enabled=False)]),
        ])

    def _panel_dir(self):
        b = self._b
        disp = b.dirDisplayChanged
        as_int = dict(enc=lambda v: str(int(float(v))) if v is not None else None,
                      dec=lambda d: int(float(d)) if d is not None else 0)

        self._c_ref_az = self._combo('ref_az', 62, "Azimuth de referencia para normalizar (0° = frente)", **as_int)
        self._c_ref_th = self._combo('ref_th', 62, "Elevación de referencia para normalizar (0° = plano horizontal)", **as_int)
        self._c_nota = self._combo('nota', 130, "Nota a graficar, o 'Todo el audio'",
                                   [("Todo el audio", "Todo el audio")], disp)
        self._c_el = self._combo('el_idx', 84, "Elevación del corte polar 2D (sólo plano XY)",
                                 [("Auto (0°)", 0)], disp,
                                 enc=lambda v: 0 if v is None else v + 1,
                                 dec=lambda d: None if d == 0 else d - 1)

        def on_plane(_=None):
            self._c_el.setEnabled(b.state.get('polar_plane', 'XY') == 'XY')
            disp()

        self._c_plane = self._combo('polar_plane', 128, "Plano del corte polar 2D",
                                    [("XY (horizontal)", "XY"), ("XZ (vert. 0°/180°)", "XZ"),
                                     ("YZ (vert. 90°/270°)", "YZ")], on_plane)
        self._dir_status = QLabel("Sin datos.")
        self._dir_status.setObjectName("rb_status")
        self._dir_status.setWordWrap(True)
        return self._panel([
            ("Cálculo", [
                ("Bandas", self._combo('bands', 96, "Resolución frecuencial",
                                       [("1/3 de octava", "1/3"), ("Octava", "octave")])),
                ("Rango (Hz)", self._pair(self._num('hz_min', 52, "Frecuencia mínima a mostrar (Hz)", disp),
                                          self._num('hz_max', 56, "Frecuencia máxima a mostrar (Hz)", disp))),
                ("Ref. azimut", self._c_ref_az),
                ("Ref. elevación", self._c_ref_th),
                (None, self._button("▶ Calcular", "Calcula el patrón de directividad. Se recomienda haber aplicado la calibración (Procesamiento ▸ Calibración)",
                                    lambda: b.computeDir(), 'compute', primary=True, enabled=False)),
                (None, self._dir_status)]),
            ("Nota", [(None, self._c_nota)]),
            ("Polar 2D", [
                ("Plano", self._c_plane),
                ("Elevación", self._c_el),
                ("Simetría", self._combo('symmetry', 112, "Simetría: espeja los datos medidos para completar el patrón",
                                         [("Sin simetría", "none"), ("XZ (izq↔der)", "azimuth"),
                                          ("XY (sup↔inf)", "elevation"), ("XZ + XY", "both")], disp))]),
            ("Paleta de color", [
                (None, self._combo('colorscale', 84, "Paleta de colores de los gráficos 3D y esfera",
                                   [(c, c) for c in ("Plasma", "Viridis", "Turbo", "Inferno", "Magma", "Cividis")], disp))]),
            ("Espectro", [
                ("Audio", self._with_info(
                    self._combo('spec_data', 130, "Señales originales, o igualadas en nivel para comparar la forma espectral",
                                [("Originales", 0), ("Igualados en nivel", 1)], disp),
                    "Espectro: Originales / Igualados en nivel", '<b>Originales</b><br>Espectro del micrófono de referencia en cada toma, tal como se midió. Incluye las diferencias de nivel con que el cantante emitió en cada toma.<br><br><b>Igualados en nivel</b><br>Espectro después de la corrección de emisión que usa el cálculo de directividad: se compensa, banda por banda, la diferencia de nivel de cada toma respecto de la toma de referencia (Ref. azimut). Así todas las tomas quedan al mismo nivel y solo importa la forma del espectro, no cuánto cantó más fuerte o más suave en cada toma.<br><br>Como la corrección se calcula con ese mismo micrófono, en <i>Igualados</i> todas las tomas coinciden; la vista Por toma sirve sobre todo con <i>Originales</i>.')),
                ("Curvas", self._combo('spec_global', 84, "Global: promedio de todos los ángulos. Por toma: una curva por azimuth",
                                       [("Global", True), ("Por toma", False)], disp))]),
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
        self._fill(self._c_ref_az, az_items, 'ref_az')
        self._fill(self._c_ref_th, [(tl(t), tv(t)) for t in thetas if t != 'ref'], 'ref_th')

        is_spl = bool(getattr(ma, '_is_spl', False))
        for n in ('hpf', 'align_takes', 'align_ref', 'detect'):
            self._btn[n].setEnabled(True)
        self._btn['compute'].setEnabled(True)      # sin calibrar se puede calcular, con aviso (ver MainWindow)
        self._act['calibrar'].setEnabled(True)
        self._act['align_takes'].setEnabled(True)
        self._act['align_mics'].setEnabled(True)
        self._act['save_tensor'].setEnabled(True)

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
        self._fill(self._c_nota, [("Todo el audio", "Todo el audio")] + [(n, n) for n in notes], 'nota')

    def set_dir_computed(self, thetas):
        self._fill(self._c_el, [("Auto (0°)", 0)] + [(f'{round(float(t))}°', i + 1) for i, t in enumerate(thetas)])
        self._c_el.setCurrentIndex(0)
        self._b.state['el_idx'] = None
        for n in ('save_polar', 'save_session', 'export_all'):
            self._act[n].setEnabled(True)

    def set_dir_status(self, text: str):
        self._dir_status.setText(text.replace('\n', ' · '))

    def get_dir_display_params(self) -> dict:
        s = self._b.state
        return dict(
            hz_min      = float(s.get('hz_min', 315.0)),
            hz_max      = float(s.get('hz_max', 10000.0)),
            colorscale  = str(s.get('colorscale', 'Plasma')),
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
