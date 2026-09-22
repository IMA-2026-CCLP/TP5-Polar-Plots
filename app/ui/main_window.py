"""
ui/main_window.py — Ventana principal con Ribbon global + QStackedWidget.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QDockWidget, QTextEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFileDialog, QToolButton, QApplication, QLineEdit, QPushButton, QLabel, QProgressBar, QMessageBox, QCheckBox, QComboBox,
)
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QFont, QTextCursor

from core.worker import Worker, activity

from version                 import __version__, APP_NAME
from ui.styles               import QSS, get_qss
from ui.native_ribbon        import NativeRibbon
from ui                      import theme as _theme
from ui.file_loader          import FileLoader
from ui.tab_preprocesamiento import TabPreprocesamiento
from ui.tab_calibracion      import TabCalibracion
from ui.tab_notas            import TabNotas, ScaleEditorDialog
from ui.tab_directividad     import TabDirectividad
from core.data_store         import load_results, save_results


class _NotasWindow(QWidget):
    """Ventana no modal de Notas: parámetros de detección arriba y la vista de segmentos/F0 abajo."""
    def __init__(self, params: QWidget, view: QWidget, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Detección de notas")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(params)
        lay.addWidget(view, 1)
        avail = self.screen().availableGeometry()
        self.resize(min(1000, avail.width() - 40), min(680, avail.height() - 40))


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{__version__}")
        # Mínimos y tamaño inicial acotados a la pantalla disponible (sin taskbar):
        # un mínimo fijo de 1200x750 no entraba en 1366x768.
        avail = self.screen().availableGeometry()
        self.setMinimumSize(min(900, avail.width()), min(560, avail.height()))
        self.resize(min(1440, avail.width()), min(860, avail.height()))
        self.setStyleSheet(QSS)

        self._ma       = None
        self._session_path: str | None = None   # último .cclp guardado/cargado — "Guardar" reusa esto
        self._settings = QSettings("AcousticTools", "PolarAnalyzerV2")
        import plot.balloon as _balloon
        _balloon.set_theme(_theme.LIGHT)   # gráficos siempre en claro (fondo blanco), aunque la app esté en oscuro

        self._build_ui()
        self._connect_ribbon()
        self._restore_geometry()

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # Vistas de contenido
        self.loader          = FileLoader(self._settings, self)
        self.view_prepro     = TabPreprocesamiento()
        self.view_notas      = TabNotas()
        self.view_dir        = TabDirectividad()

        # Ribbon
        self.ribbon = NativeRibbon()

        # Stack de contenido
        self._stack = QStackedWidget()
        self._stack.addWidget(self.view_prepro)     # 0  (home)
        self._stack.addWidget(self.view_dir)        # 1
        # La ventana se muestra por primera vez con las vistas web (Directividad) visibles y recién después
        # vuelve a Procesamiento (ver showEvent): si esas vistas se muestran más tarde, Qt recrea la ventana
        # y la app parece cerrarse y reabrirse ("pantallazo") al cambiar de pestaña o graficar.
        self._stack.setCurrentIndex(1)
        self._first_show = True

        # Layout central
        # Menú + pestañas arriba a todo el ancho; parámetros en un dock movible a la izquierda
        self.setMenuWidget(self.ribbon)
        self.setCentralWidget(self._stack)
        self._params_stack = QStackedWidget()
        self._params_stack.addWidget(self.ribbon.proc_panel)     # 0
        self._params_stack.addWidget(self.ribbon.dir_panel)      # 1
        self._params_dock = QDockWidget("Parámetros", self)
        self._params_dock.setWidget(self._params_stack)
        self._params_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                      QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                                      QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._params_dock)
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.resizeDocks([self._params_dock], [300], Qt.Orientation.Horizontal)
        self.ribbon.add_view_action(self._params_dock.toggleViewAction())
        self.notas_win = _NotasWindow(self.ribbon.notas_page, self.view_notas, self)

        self._setup_log_dock()

        self._update_statusbar_style(_theme.current())
        self.statusBar().showMessage("Listo — Archivo ▸ Cargar audio… para empezar.")

        # Indicador de operación en curso (el log está oculto por defecto)
        self._op_label = QLabel()
        self._op_bar = QProgressBar()
        self._op_bar.setRange(0, 0)                 # animación "ocupado"
        self._op_bar.setFixedSize(170, 12)
        self._op_bar.setTextVisible(False)
        self.statusBar().addPermanentWidget(self._op_label)
        self.statusBar().addPermanentWidget(self._op_bar)
        self._op_label.hide()
        self._op_bar.hide()
        activity.changed.connect(self._on_activity)
        activity.progress.connect(self._on_progress)
        self._op_base = ""

    # ── Conexiones ────────────────────────────────────────────────────────────

    def _connect_ribbon(self):
        rb = self.ribbon

        # Navegación
        rb.tab_changed.connect(self._on_tab_changed)
        # ── Archivo
        rb.sig_load_audio.connect(lambda: self.loader.load_audio(self))
        rb.sig_edit_patterns.connect(lambda: self.loader.edit_patterns(self))
        rb.sig_open_notas.connect(self._open_notas)
        rb.sig_open_options.connect(self._open_graph_options)
        rb.sig_save_session.connect(self._on_save_session)
        rb.sig_save_session_as.connect(self._on_save_session_as)
        rb.sig_load_session.connect(self._on_load_session)

        # ── Procesamiento
        rb.sig_plot_params.connect(self._on_plot_params)
        rb.sig_apply_hpf.connect(self._on_apply_hpf)
        rb.sig_align_takes.connect(self._on_align_takes)
        rb.sig_align_preview.connect(self._on_align_preview)
        rb.sig_align_ref.connect(self._on_align_ref)
        rb.sig_open_calibracion.connect(self._open_calibracion_dialog)

        # ── Notas
        rb.sig_detect_notes.connect(self._on_detect_notes)
        rb.sig_edit_scale.connect(self._on_edit_scale)
        rb.sig_preset_changed.connect(self.view_notas._set_scale_from_preset)
        rb.sig_save_mask.connect(self._on_save_mask)
        rb.sig_load_mask.connect(self._on_load_mask)

        # ── Directividad
        rb.sig_compute_dir.connect(self._on_compute_dir)
        rb.sig_export_all_images.connect(self._on_export_all_images)
        rb.sig_dir_display_changed.connect(self._on_dir_display_changed)

        # ── Tema
        rb.sig_theme_toggled.connect(self._toggle_theme)

        # ── Señales de retorno de las vistas
        self.loader.ma_ready.connect(self._on_ma_ready)
        self.loader.log.connect(self._append_log)

        self.view_prepro.ma_updated.connect(self._on_ma_ready)
        self.view_prepro.log.connect(self._append_log)

        self.view_notas.ma_updated.connect(self._on_ma_ready)
        self.view_notas.log.connect(self._append_log)
        self.view_notas.log.connect(self._on_notas_log)

        self.view_dir.log.connect(self._append_log)
        self.view_dir.computed.connect(self._on_dir_computed)
        self.view_dir.compute_finished.connect(lambda: QTimer.singleShot(0, self._offer_save_directivity))

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        import plot.balloon as _balloon
        p = _theme.toggle()
        qss = get_qss(p)
        QApplication.instance().setStyleSheet(qss)
        self.setStyleSheet(qss)
        self.ribbon._update_theme_icon(p)
        self._update_statusbar_style(p)
        self.view_dir.apply_theme(p)
        self.view_notas.apply_theme(p)
        self.view_prepro.apply_theme(p)

    def _update_statusbar_style(self, p: dict):
        self.statusBar().setStyleSheet(
            f"QStatusBar {{ background: {p['bg_dark']}; border-top: 1px solid {p['border']};"
            f" color: {p['text_muted']}; font-size: 8.5pt; padding: 0 12px; }}"
        )

    # ── Slots de navegación ───────────────────────────────────────────────────

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self._op_bar.setRange(0, total)
            self._op_bar.setValue(done)
            self._op_label.setText(f"{self._op_base}  {100 * done // total} %")

    def _on_activity(self, n: int, label: str):
        busy = n > 0
        self._op_base = label + (f"  (+{n - 1} más)" if n > 1 else "")
        self._op_bar.setRange(0, 0)          # animación "ocupado" hasta que llegue el primer progreso
        self._op_label.setText(self._op_base)
        self._op_label.setVisible(busy)
        self._op_bar.setVisible(busy)

    def _on_tab_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self._params_stack.setCurrentIndex(idx)

    def _open_graph_options(self, kind: str):
        """Opciones ▸ Gráficos ▸ …: el mismo modal de Propiedades del gráfico (o el de Imágenes)."""
        if kind == "images":
            from ui.options_dialogs import ImageOptionsDialog
            ImageOptionsDialog(self).exec()
            return
        self.ribbon._switch_tab(1)          # Directividad
        self.view_dir._show_properties_panel(kind)

    def _open_notas(self):
        self.notas_win.show()
        self.notas_win.raise_()
        self.notas_win.activateWindow()

    # ── Slots de Archivo ──────────────────────────────────────────────────────

    # Sesión .cclp: mismo contenido que la directividad .npz (core/data_store.py), sin audio, más
    # el estado COMPLETO de la interfaz (no sólo los controles de Directividad). Ver core/session.py.

    def _on_load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar sesión", "", "Sesión CCLP (*.cclp)")
        if path:
            self._load_polar_npz_file(path)
            self._session_path = path

    def _load_polar_npz_file(self, path: str):
        try:
            data = load_results(path)
            view = data['metadata'].get('view') or {}
            # Cambiar a Directividad ANTES de cargar para que las secciones
            # sean visibles cuando _refresh_display() las actualice
            self.ribbon._switch_tab(1)
            notes = self.view_dir.load_from_npz(data)
            self.ribbon.set_dir_computed(data['thetas'])
            self.ribbon.set_notes_loaded(notes)
            if view.get('session_ui'):                # todo el estado de la interfaz
                self.ribbon.apply_ui_state(view['session_ui'])
            if view.get('view_dir'):                   # propiedades de cada gráfico
                self.view_dir.apply_view_config(view['view_dir'])
            self.view_dir.apply_display_params(self.ribbon.get_dir_display_params())
            self.ribbon.set_dir_status(
                f"Cargado sin audios\n{data['dir_freqs'][0]:.0f}–{data['dir_freqs'][-1]:.0f} Hz"
            )
            self._append_log(f"[Sesión] Cargado desde {path}")
        except Exception as e:
            self._append_log(f"[ERROR] Al cargar sesión: {e}")

    def _on_save_session(self):
        """Guardar: si ya se guardó/cargó un .cclp en esta sesión de trabajo, sobrescribe ese mismo
        archivo sin preguntar (como Ctrl+S en cualquier editor). Si no, se comporta como 'Guardar como…'."""
        if self._session_path is None:
            self._on_save_session_as()
            return
        ma = self._get_ma_for_session()
        if ma is not None:
            self._save_polar_npz_file(self._session_path, ma)

    def _on_save_session_as(self):
        ma = self._get_ma_for_session()
        if ma is None:
            return
        start = self._session_path or (str(self._settings.value("last_polar_dir", "")) + "/sesion.cclp")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar sesión como", start, "Sesión CCLP (*.cclp)")
        if path:
            self._settings.setValue("last_polar_dir", str(Path(path).parent))
            self._save_polar_npz_file(path, ma)
            self._session_path = path

    def _get_ma_for_session(self):
        # OJO: self._ma sólo se actualiza al cargar/preprocesar/calibrar
        # audio (_on_ma_ready) — la directividad (global y por nota) se
        # calcula adentro de TabDirectividad, que mantiene su propia
        # referencia (compartida al principio, pero divergente en cuanto
        # se computan notas). Hay que usar view_dir.get_ma(), si no el
        # guardado queda bloqueado o sin notas cuando sólo se computó por
        # nota (sin pasar nunca por "Todo el audio").
        ma = self.view_dir.get_ma()
        has_global = ma is not None and ma.dir_levels is not None
        has_notes  = ma is not None and ma.notes and any(
            n.dir_levels is not None for n in ma.notes.values())
        if not has_global and not has_notes:
            self._append_log("[Sesión] Nada calculado todavía: no hay datos de gráficos para guardar "
                              "(usar Calcular en Directividad primero).")
            return None
        return ma

    def _save_polar_npz_file(self, path: str, ma):
        try:
            rb = self.ribbon
            st = rb._bridge.state
            view = {
                'view_dir':   self.view_dir.get_view_config(),
                'session_ui': st.copy(),    # todo el estado de la interfaz, no sólo Directividad
            }
            save_results(
                filepath       = path,
                ma             = ma,
                bands          = rb.combo_bands.currentText(),
                ref_azimuth    = int(float(rb.le_ref_az.text() or 0)),
                ref_theta_plot = int(float(rb.le_ref_th.text() or 0)),
                view           = view,
            )
            self._append_log(f"[Sesión] Guardado → {path}")
        except Exception as e:
            self._append_log(f"[ERROR] Al guardar sesión: {e}")

    # ── Slots de Procesamiento ────────────────────────────────────────────────

    def _on_plot_params(self, theta, azimuth, env, db, yrange, smoothing):
        self.view_prepro.refresh_plot(theta, azimuth, env, db, yrange, smoothing)

    def _on_apply_hpf(self, hz: float):
        self.view_prepro.apply_hpf(hz)

    def _on_align_takes(self, onset, thresh, theta, window_ms):
        self.view_prepro.align_takes(onset, thresh, theta, window_ms)

    def _on_align_preview(self, onset, thresh, theta):
        self.view_prepro.set_align_params(onset, thresh, theta)

    def _on_align_ref(self, gcc_thresh):
        self.view_prepro.align_ref(gcc_thresh)

    def _on_to_spl(self):
        if self._ma is None or self._ma._is_spl:
            return

        def _run():
            self._ma.to_spl()
            return self._ma

        def _done(ma):
            self._on_ma_ready(ma)
            self._append_log("[Calibración] Tensor convertido a SPL (Pa).")

        def _err(msg):
            self._append_log(f"[ERROR] to_spl:\n{msg}")

        self._spl_worker = Worker(_run)
        self._spl_worker.label = "Convirtiendo a dB SPL…"
        self._spl_worker.finished.connect(_done)
        self._spl_worker.error.connect(_err)
        self._spl_worker.log.connect(self._append_log)
        self._spl_worker.start()

    def _open_calibracion_dialog(self):
        if self._ma is None:
            return
        dlg = _CalibracionDialog(self._ma, self)

        def applied(ma):                 # calibrar => pasar a dB SPL en el mismo paso
            self._on_ma_ready(ma)
            dlg.accept()
            self._on_to_spl()

        dlg.ma_updated.connect(applied)
        dlg.log.connect(self._append_log)
        dlg.exec()

    # ── Slots de Notas ────────────────────────────────────────────────────────

    def _on_detect_notes(self, tol, purity, start_s, grad, ref_theta):
        self.view_notas.detect_notes(tol, purity, start_s, grad, ref_theta)

    def _on_notas_log(self, msg: str):
        if "Detección completada" in msg or "Máscara cargada" in msg:
            self.ribbon.btn_save_mask.setEnabled(True)

    def _on_edit_scale(self):
        dlg = ScaleEditorDialog(self.view_notas.get_scale(), self.ribbon.current_scale_name(), self.notas_win)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        if dlg.db_changed or (accepted and dlg.selected_name):
            self.ribbon.refresh_scales(dlg.selected_name)      # actualiza el combo (y elige la escala)
        if accepted:
            self.view_notas.set_scale(dlg.get_scale())         # pisa con lo que quedó en la tabla (ediciones sin guardar)

    def _on_save_mask(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar máscara de segmentos", "", "Máscara (*.msk)"
        )
        if path:
            if not path.lower().endswith('.msk'):
                path += '.msk'
            self.view_notas.save_mask(path)

    def _on_load_mask(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar máscara de segmentos", "", "Máscara (*.msk);;JSON antiguo (*.json)"
        )
        if path:
            self.view_notas.load_mask(path)
            self.ribbon.btn_save_mask.setEnabled(True)

    # ── Slots de Directividad ─────────────────────────────────────────────────

    def _on_compute_dir(self, bands, hz_min, hz_max, ref_az, ref_th):
        if not self._confirm_uncalibrated():
            return
        self.view_dir.compute_all(bands, hz_min, hz_max, ref_az, ref_th)

    def _confirm_uncalibrated(self) -> bool:
        """Calcular sin calibrar está permitido, pero se advierte de la limitación (True = continuar)."""
        ma = self.view_dir.get_ma() or self._ma
        if ma is None or ma._is_spl:
            return True
        box = QMessageBox(QMessageBox.Icon.Warning, "Calibración no aplicada", "", parent=self)
        box.setText("No se aplicó la calibración de los micrófonos.")
        box.setInformativeText(
            "En mediciones con múltiples micrófonos, la sensibilidad de cada canal puede diferir "
            "(del orden de 1 a 3 dB). Sin calibrar, esas diferencias no se corrigen y se confunden "
            "con directividad real, por lo que los resultados pueden no ser adecuados para un análisis "
            "cuantitativo.\n\n"
            "Los niveles se expresarán en dBFS (no en dB SPL) y el patrón quedará relativo a la "
            "posición de referencia.\n\n"
            "Si la medición se hizo con un único micrófono, o con canales de sensibilidad equivalente, "
            "el efecto es despreciable."
        )
        btn_go = box.addButton("Ok, continuar", QMessageBox.ButtonRole.AcceptRole)
        btn_cal = box.addButton("Calibrar", QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(btn_cal)      # cerrar la ventana (Esc / X) cancela el cálculo
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_cal:
            self._open_calibracion_dialog()
            return False
        return clicked is btn_go

    def _on_export_all_images(self):
        if self.view_dir._full_bands is None:
            self._append_log("[Dir] Sin datos para exportar.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Exportar imágenes de directividad")
        form = QFormLayout(dlg)

        checks = {}
        box = QVBoxLayout()
        for mode, label in (("polar2d", "Polar 2D"), ("spectrum", "Espectro"),
                            ("3d", "Superficie 3D"), ("sphere", "Esfera")):
            cb = QCheckBox(label)
            cb.setChecked(True)
            checks[mode] = cb
            box.addWidget(cb)
        form.addRow("Gráficos:", box)

        le_prefix = QLineEdit("directividad")
        form.addRow("Nombre base:", le_prefix)

        from ui.export_utils import get_last_export_dir, set_last_export_dir
        le_folder = QLineEdit(get_last_export_dir())
        le_folder.setReadOnly(True)
        btn_browse = QPushButton("Examinar…")

        def _browse():
            d = QFileDialog.getExistingDirectory(dlg, "Carpeta de destino", le_folder.text())
            if d:
                le_folder.setText(d)
        btn_browse.clicked.connect(_browse)

        row = QHBoxLayout()
        row.addWidget(le_folder)
        row.addWidget(btn_browse)
        form.addRow("Carpeta:", row)

        from ui import export_utils as _eu
        w_cm, h_cm = _eu.get_export_size_cm()
        dpi0, fmt0 = _eu.get_export_defaults()
        le_dpi = QLineEdit(str(dpi0))
        le_dpi.setFixedWidth(70)
        le_dpi.setToolTip("Calidad de la imagen (píxeles por pulgada). No cambia el tamaño físico, sólo la nitidez. "
                          "Se guarda también en el archivo. Valor típico: 300.")
        form.addRow("DPI:", le_dpi)
        lbl_size = QLabel()
        lbl_size.setObjectName("rb_status")
        lbl_size.setToolTip("Se cambia en Opciones ▸ Gráficos ▸ Imágenes")

        def _upd_size(*_):
            try:
                d = max(72.0, min(1200.0, float(le_dpi.text().replace(',', '.'))))
            except ValueError:
                d = float(dpi0)
            lbl_size.setText(f"Tamaño fijo {w_cm:g} × {h_cm:g} cm = {round(w_cm / 2.54 * d)} × {round(h_cm / 2.54 * d)} px "
                             "(Opciones ▸ Gráficos ▸ Imágenes)")
        le_dpi.textChanged.connect(_upd_size)
        _upd_size()
        form.addRow(lbl_size)

        combo_fmt = QComboBox()
        combo_fmt.addItem("PNG (imagen)", "png")
        combo_fmt.addItem("SVG (vectorial) — solo Polar 2D", "svg")
        combo_fmt.setToolTip("SVG no se pixela al ampliar. Espectro, Superficie 3D y Esfera se exportan siempre en PNG.")
        combo_fmt.setCurrentIndex(max(0, combo_fmt.findData(fmt0)))
        form.addRow("Formato:", combo_fmt)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        modes = [m for m, cb in checks.items() if cb.isChecked()]
        if not modes:
            self._append_log("[Dir] Exportación cancelada: no se eligió ningún gráfico.")
            return
        prefix = le_prefix.text().strip() or "directividad"
        folder = le_folder.text().strip()
        if not folder:
            self._append_log("[Dir] Exportación cancelada: no se eligió carpeta.")
            return
        set_last_export_dir(folder)

        try:
            dpi = int(float(le_dpi.text().strip().replace(',', '.') or 300))
        except ValueError:
            dpi = 300
        dpi = max(72, min(1200, dpi))
        self.view_dir.export_all_images(folder, prefix, dpi=dpi, modes=modes, fmt=combo_fmt.currentData())

    def _on_dir_display_changed(self):
        params = self.ribbon.get_dir_display_params()
        self.view_dir.apply_display_params(params)

    def _offer_save_directivity(self):
        """Tras Calcular: ofrece guardar el archivo de directividad (elige la ubicación en el diálogo de archivo)."""
        ma = self.view_dir.get_ma()
        if ma is None or ma.dir_levels is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Directividad calculada")
        box.setText("¿Querés guardar la sesión?")
        box.setInformativeText("Así podés volver a ver los gráficos más adelante sin reprocesar los audios.")
        btn_save = box.addButton("Guardar…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec()
        if box.clickedButton() is btn_save:
            self._on_save_session()

    def _on_dir_computed(self, thetas, status: str):
        self.ribbon.set_dir_computed(thetas)
        self.ribbon.set_dir_status(status)

    # ── Propagación de MicArray ───────────────────────────────────────────────

    def _on_ma_ready(self, ma):
        self._ma = ma
        shape = ma.tensor.shape
        self.statusBar().showMessage(
            f"Tensor {shape}  ·  sr {ma.sr} Hz  ·  "
            f"Cal: {'OK' if ma.calibration is not None else '—'}  ·  "
            f"SPL: {'OK' if ma._is_spl else '—'}"
        )
        # Primero inyectar ma en las vistas para que estén listas
        # antes de que ribbon dispare _emit_plot_params()
        self.view_prepro.set_ma(ma)
        self.view_notas.set_ma(ma)
        self.view_dir.set_ma(ma)

        self.ribbon.set_ma_loaded(ma)
        if ma.notes:
            self.ribbon.set_notes_loaded(list(ma.notes.keys()))
        if ma.dir_levels is not None:
            self.ribbon.set_dir_computed(ma.dir_freqs)
            self.ribbon.set_dir_status("Sesión cargada")

    # ── Log ───────────────────────────────────────────────────────────────────

    def _setup_log_dock(self):
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMinimumHeight(48)

        self._log_dock = QDockWidget("Log", self)
        self._log_dock.setWidget(self._log)
        self._log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self.ribbon.add_view_action(self._log_dock.toggleViewAction())
        # altura inicial proporcional a la pantalla (150 px fijos se comían el gráfico en 768p)
        self.resizeDocks([self._log_dock], [max(60, int(self.screen().availableGeometry().height() * 0.12))],
                         Qt.Orientation.Vertical)

        # ajustar restricciones de tamaño según dónde está anclado
        self._log_dock.dockLocationChanged.connect(self._on_log_dock_location)
        self._log_dock.topLevelChanged.connect(self._on_log_floating)

        self._log_dock.hide()      # oculto por defecto; se abre desde Ver ▸ Log

    def _on_log_dock_location(self, area):
        _MAX = 16_777_215
        sides = (Qt.DockWidgetArea.LeftDockWidgetArea,
                 Qt.DockWidgetArea.RightDockWidgetArea)
        if area in sides:
            self._log_dock.setMaximumHeight(_MAX)
            self._log_dock.setMaximumWidth(320)
        else:
            self._log_dock.setMaximumHeight(300)
            self._log_dock.setMaximumWidth(_MAX)

    def _on_log_floating(self, floating: bool):
        _MAX = 16_777_215
        if floating:
            self._log_dock.setMaximumHeight(_MAX)
            self._log_dock.setMaximumWidth(_MAX)

    def _append_log(self, text: str):
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text + "\n")
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _restore_geometry(self):
        geom = self._settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            QTimer.singleShot(0, lambda: self._stack.setCurrentIndex(self.ribbon._tabs.currentIndex()))

    def closeEvent(self, event):
        self._settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)


# ── Diálogo de Calibración ────────────────────────────────────────────────────

from PyQt6.QtCore import pyqtSignal as _Signal

class _CalibracionDialog(QDialog):
    ma_updated = _Signal(object)
    log        = _Signal(str)

    def __init__(self, ma, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibración")
        self.setMinimumSize(520, 400)
        self.setModal(True)

        self._cal_widget = TabCalibracion()
        self._cal_widget.set_ma(ma)
        self._cal_widget.ma_updated.connect(self.ma_updated)
        self._cal_widget.log.connect(self.log)

        lay = QVBoxLayout(self)
        lay.addWidget(self._cal_widget, 1)
