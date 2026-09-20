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
from PyQt6.QtGui import QAction, QDoubleValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QTabBar, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QFrame, QToolButton,
)

from ui.bridge import Bridge
from ui import theme as _theme

_TABS = [
    ("Procesamiento", "Visualizar señales, aplicar filtros y alinear tomas"),
    ("Notas",         "Detectar y segmentar notas musicales en el audio"),
    ("Directividad",  "Calcular y visualizar el patrón de directividad acústica"),
]
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
    sig_save_tensor     = pyqtSignal()
    sig_load_tensor     = pyqtSignal()
    sig_load_polar_npz  = pyqtSignal()
    sig_save_polar_npz  = pyqtSignal()

    sig_apply_hpf        = pyqtSignal(float)
    sig_align_takes      = pyqtSignal(float, float, object, float)
    sig_align_preview    = pyqtSignal(float, float, object)
    sig_align_ref        = pyqtSignal(object)
    sig_open_calibracion = pyqtSignal()
    sig_to_spl           = pyqtSignal()
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
        self._pages = [self._page_proc(), self._page_notas(), self._page_dir()]
        for p in self._pages:
            lay.addWidget(p)
        line = QFrame()
        line.setObjectName("rb_line")
        line.setFixedHeight(1)
        lay.addWidget(line)

        # Proxies de compatibilidad con MainWindow
        self.btn_to_spl    = self._act['to_spl']
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
            'sig_load_polar_npz', 'sig_save_polar_npz', 'sig_apply_hpf', 'sig_align_takes',
            'sig_align_preview', 'sig_align_ref', 'sig_open_calibracion', 'sig_to_spl',
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

    def _chk(self, text, key, tip, cb=None):
        c = QCheckBox(text)
        c.setToolTip(tip)

        def load():
            c.blockSignals(True)
            c.setChecked(bool(self._b.state.get(key)))
            c.blockSignals(False)

        def toggled(on):
            self._b.state[key] = on
            if cb:
                cb()

        c.toggled.connect(toggled)
        c._load = load
        self._loaders.append(load)
        load()
        return c

    def _pill(self, text, key, tip, default):
        b = QPushButton(text)
        b.setObjectName("pill")
        b.setCheckable(True)
        b.setToolTip(tip)

        def load():
            b.blockSignals(True)
            b.setChecked(bool(self._b.state.get(key, default)))
            b.blockSignals(False)

        def toggled(on):
            self._b.state[key] = on
            self._b.dirDisplayChanged()

        b.toggled.connect(toggled)
        self._loaders.append(load)
        load()
        return b

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
        act('load_tensor', "Cargar sesión…",  "Carga una sesión (.cclp) o tensor (.npz) guardado", b.loadTensor)
        act('save_tensor', "Guardar sesión…", "Guarda tensor + calibración + notas + directividad en .cclp", b.saveTensor, False)
        act('load_polar',  "Cargar NPZ polar…", "Carga resultados de directividad exportados (.npz)", b.loadPolarNpz)
        act('save_polar',  "Guardar NPZ polar…", "Exporta solo los resultados de directividad calculados (.npz)", b.savePolarNpz, False)
        act('calibrar',    "Calibrar…",       "Ingresar los niveles de calibración de cada micrófono", b.openCalibracion, False)
        act('to_spl',      "Convertir a SPL", "Convierte el tensor (FS) a presión sonora usando la calibración cargada", b.toSpl, False)
        act('save_mask',   "Guardar máscara…", "Guarda la segmentación de notas detectadas", b.saveMask, False)
        act('load_mask',   "Cargar máscara…", "Carga una segmentación de notas guardada", b.loadMask)
        act('save_dir',    "Exportar NPZ",    "Exporta el patrón de directividad calculado (.npz)", b.saveDirNpz, False)
        act('export_all',  "Exportar imágenes", "Exporta las imágenes de todas las vistas habilitadas para todas las bandas", b.exportAllImages, False)
        act('edit_scale',  "Editar escala…",  "Crear o modificar una escala musical", b.editScale)

    def _make_menubar(self) -> QMenuBar:
        mb = QMenuBar()
        m = mb.addMenu("&Archivo")
        for n in ('load_audio', 'patterns', 'load_tensor', 'save_tensor'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('load_polar', 'save_polar'):
            m.addAction(self._act[n])
        m.addSeparator()
        m.addAction("Salir", lambda: self.window().close())

        m = mb.addMenu("&Ver")
        self._act_dark = QAction("Tema oscuro", self)
        self._act_dark.setCheckable(True)
        self._act_dark.setChecked(_theme.is_dark())
        self._act_dark.triggered.connect(lambda _=False: self.sig_theme_toggled.emit())
        m.addAction(self._act_dark)

        m = mb.addMenu("&Herramientas")
        for n in ('calibrar', 'to_spl'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('edit_scale', 'save_mask', 'load_mask'):
            m.addAction(self._act[n])
        m.addSeparator()
        for n in ('save_dir', 'export_all'):
            m.addAction(self._act[n])
        return mb

    def _make_tabbar(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(6, 0, 8, 0)
        self._tabs = QTabBar()
        self._tabs.setObjectName("main_tabs")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
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
        for k, p in enumerate(self._pages):
            p.setVisible(k == i)
        self._b.tabClicked(i)

    # ── Páginas ───────────────────────────────────────────────────────────
    def _page_proc(self):
        b = self._b
        plot = b.emitPlotParams
        prev = b.emitAlignPreview
        th = dict(enc=lambda v: str(v), dec=lambda d: d)

        self._c_theta = self._combo('theta', 78, "Elevación (micrófono) a visualizar", cb=plot, **th)
        self._c_az    = self._combo('az', 78, "Azimuth a visualizar, o 'Todos' para superponer las tomas", cb=plot, **th)

        def on_db(on):
            if on:
                self._chk_env.setChecked(True)
                b.state['envelope'] = True
            plot()

        self._chk_env = self._chk("Envolvente", 'envelope', "Envolvente de la señal (transformada de Hilbert)", plot)
        chk_db = self._chk("dB", 'db', "Envolvente en escala logarítmica (activa la envolvente)", on_db)
        self._c_align_th = self._combo('align_theta', 64, "Micrófono de referencia para la alineación", cb=prev, **th)
        return self._page([
            ("Vista", [
                "θ", self._c_theta, "Az", self._c_az, self._chk_env, chk_db,
                "Suav", self._num('smooth', 42, "Suavizado de la envolvente en ms", plot), "ms", '|',
                "Min", self._num('ymin', 50, "Límite inferior del eje Y. Vacío = autoescala", plot, True, "-60"),
                "Max", self._num('ymax', 50, "Límite superior del eje Y. Vacío = autoescala", plot, True, "0")]),
            ("Filtro / SPL", [
                "HPF", self._num('hpf_hz', 52, "Frecuencia de corte del pasa-altos (Hz)"), "Hz",
                self._button("Aplicar HPF", "Aplica el Butterworth pasa-altos al tensor (irreversible en memoria)",
                             lambda: b.applyHpf(), 'hpf', enabled=False), '|',
                self._tool('calibrar'), self._tool('to_spl')]),
            ("Alineación", [
                "Onset", self._num('onset', 44, "Tiempo objetivo del onset tras alinear (s)", prev), "s",
                "Umbral", self._num('thresh', 44, "Nivel mínimo para detectar el onset (dBFS)", prev), "dB",
                self._button("Alinear tomas", "Alinea las tomas por onset según el umbral",
                             lambda: b.alignTakes(), 'align_takes', enabled=False), '|',
                "Vent", self._num('window_ms', 40, "Ventana de análisis GCC-PHAT (ms)"), "ms",
                "Mic ref", self._c_align_th,
                "GCC", self._num('gcc_thresh', 48, "Nivel mínimo de la toma para GCC-PHAT (dBFS). Vacío = sin filtro",
                                 nullable=True, placeholder="dBFS"),
                self._button("Alinear mics", "Alinea los micrófonos al de referencia con GCC-PHAT",
                             lambda: b.alignRef(), 'align_ref', enabled=False)]),
        ])

    def _page_notas(self):
        b = self._b
        self._c_preset = QComboBox()
        self._c_preset.setFixedWidth(140)
        self._c_preset.setToolTip("Escala musical de referencia para detectar notas")
        self._c_preset.currentTextChanged.connect(lambda name: b.presetChanged(name) if name else None)
        from ui.tab_notas import SCALE_PRESETS
        self._c_preset.addItems(list(SCALE_PRESETS.keys()))

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

    def _page_dir(self):
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
        return self._page([
            ("Cálculo", [
                "Bandas", self._combo('bands', 96, "Resolución frecuencial",
                                      [("1/3 de octava", "1/3"), ("Octava", "octave")]),
                "Hz", self._num('hz_min', 52, "Frecuencia mínima a mostrar (Hz)", disp), "–",
                self._num('hz_max', 56, "Frecuencia máxima a mostrar (Hz)", disp),
                "Ref Az", self._c_ref_az, "Ref θ", self._c_ref_th,
                self._button("▶ Calcular", "Calcula el patrón de directividad (requiere tensor en SPL)",
                             lambda: b.computeDir(), 'compute', primary=True, enabled=False), '|',
                "Nota", self._c_nota, self._dir_status]),
            ("Vista", [
                "Color", self._combo('colorscale', 84, "Paleta de colores de los gráficos",
                                     [(c, c) for c in ("Plasma", "Viridis", "Turbo", "Inferno", "Magma", "Cividis")], disp),
                "Plano", self._c_plane, "Elev", self._c_el,
                "Sim", self._combo('symmetry', 112, "Simetría: espeja los datos medidos para completar el patrón",
                                   [("Sin simetría", "none"), ("XZ (izq↔der)", "azimuth"),
                                    ("XY (sup↔inf)", "elevation"), ("XZ + XY", "both")], disp), '|',
                self._pill("3D", 'view_3d', "Superficie 3D", False),
                self._pill("Esfera", 'view_sphere', "Esfera coloreada por nivel", True),
                self._pill("Polar 2D", 'view_polar2d', "Corte polar 2D", True),
                self._pill("Espectro", 'view_spectrum', "Espectro por azimuth", False),
                self._pill("Info", 'show_info', "Recuadro de información (banda, máx, dinámica)", True)]),
            ("Espectro", [
                "Audio", self._combo('spec_data', 130, "Señales originales, o igualadas en nivel para comparar la forma espectral",
                                     [("Originales", 0), ("Igualados en nivel", 1)], disp),
                "Vista", self._combo('spec_global', 84, "Global: promedio de todos los ángulos. Por toma: una curva por azimuth",
                                     [("Global", True), ("Por toma", False)], disp), '|',
                self._tool('save_dir'), self._tool('export_all')]),
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
        self._btn['compute'].setEnabled(is_spl)
        self._act['calibrar'].setEnabled(True)
        self._act['to_spl'].setEnabled(not is_spl)
        self._act['save_tensor'].setEnabled(True)

        sr = getattr(ma, 'sr', 0) // 1000
        self._chip_last = (f"{len(angles)} × {len(thetas)} · {sr} kHz" + (' · SPL ✓' if is_spl else ''), True)
        self._set_chip(*self._chip_last)
        self._sync()                 # numéricos/checks/pills desde state (p. ej. sesión cargada)
        self._b.emitPlotParams()
        self._b.emitAlignPreview()

    def set_notes_loaded(self, notes: list):
        self._fill(self._c_nota, [("Todo el audio", "Todo el audio")] + [(n, n) for n in notes], 'nota')

    def set_dir_computed(self, thetas):
        self._fill(self._c_el, [("Auto (0°)", 0)] + [(f'{round(float(t))}°', i + 1) for i, t in enumerate(thetas)])
        self._c_el.setCurrentIndex(0)
        self._b.state['el_idx'] = None
        for n in ('save_dir', 'save_polar', 'export_all'):
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
            show_info   = bool(s.get('show_info', True)),
            symmetry    = str(s.get('symmetry', 'none')),
            nota        = str(s.get('nota', 'Todo el audio')),
            spec_data   = int(s.get('spec_data', 0)),
            spec_global = bool(s.get('spec_global', True)),
            view_checks = {
                '3d':       bool(s.get('view_3d',       False)),
                'sphere':   bool(s.get('view_sphere',   True)),
                'polar2d':  bool(s.get('view_polar2d',  True)),
                'spectrum': bool(s.get('view_spectrum', False)),
            },
        )


_INT_KEYS = ('ref_az', 'ref_th')
