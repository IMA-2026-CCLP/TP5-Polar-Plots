"""
ui/main_window.py — Ventana principal con Ribbon global + QStackedWidget.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QDockWidget, QTextEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFileDialog, QToolButton, QApplication, QLineEdit, QPushButton, QLabel, QProgressBar, QMessageBox, QCheckBox, QComboBox,
)
from pathlib import Path
import numpy as np

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
        self._matrix_win = None   # panel de la matriz radial (Procesamiento ▸ Vista)
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
        self.view_notas.set_notas_controls(self.ribbon.notas_panel)

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
        # Ancho inicial = lo que de verdad necesitan los dos paneles (nunca debe haber un
        # deslizable horizontal: el QScrollArea lo tiene apagado a propósito, así que si el
        # dock queda angosto el contenido se recorta sin forma de verlo).
        needed = max(self.ribbon.proc_panel.widget().minimumSizeHint().width(),
                     self.ribbon.dir_panel.widget().minimumSizeHint().width()) + 24
        start_w = max(340, needed)
        self.resizeDocks([self._params_dock], [start_w], Qt.Orientation.Horizontal)
        self._params_dock.setMinimumWidth(start_w)   # resizeDocks solo no sobrevive el primer layout
        self.ribbon.add_view_action(self._params_dock.toggleViewAction())

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
        rb.sig_export_all_images.connect(self._on_export_all_images)
        rb.sig_dir_display_changed.connect(self._on_dir_display_changed)
        rb.sig_intersect_cut3d.connect(self._on_intersect_cut3d)

        # ── Tema
        rb.sig_theme_toggled.connect(self._toggle_theme)

        # ── Señales de retorno de las vistas
        self.loader.ma_ready.connect(self._on_ma_ready)
        self.loader.ma_ready.connect(lambda _ma: self.ribbon.clear_done())   # audio nuevo: pasos sin hacer
        self.loader.ma_ready.connect(lambda _ma: setattr(self, '_mask_asked', False))
        self.view_prepro.set_sample_widget(self.ribbon._c_nota_proc)     # Muestra: toda / cada nota, junto a Vista y Frecuencia
        self.view_prepro.op_done.connect(self.ribbon.mark_done)
        self.view_dir.step_done.connect(self.ribbon.mark_done)
        self.loader.log.connect(self._append_log)

        self.view_prepro.ma_updated.connect(self._on_ma_ready)
        self.view_prepro.log.connect(self._append_log)
        self.view_prepro.view_chosen.connect(self._on_view_choice)
        self.ribbon._b.sig_corr_recalc.connect(self._on_corr_recalc)
        self.ribbon._b.sig_filter_bands.connect(self._on_filter_bands)
        self.ribbon._b.sig_nivelar_onaxis.connect(self._on_nivelar_onaxis)
        self.ribbon._b.sig_matrix_grid.connect(self._on_matrix_grid)
        self.ribbon._b.sig_save_grid.connect(self._on_save_grid)
        self.ribbon._b.sig_load_grid.connect(self._on_load_grid)
        self.view_dir.grid_state = self.ribbon._b.state   # suavizado/interpolación de la matriz (en vivo)
        self.view_prepro._editor.set_corr_offset(self._corr_offset_db)
        QTimer.singleShot(0, self.ribbon._b.emitPlotParams)   # al abrir: matriz radial (esqueleto si no hay datos)
        self.view_dir.on_data_changed = self._refresh_matrix     # datos nuevos → matriz (si es la vista activa)

        self.view_notas.ma_updated.connect(self._on_ma_ready)
        self.view_notas.log_loaded_mask.connect(self.view_notas.show_f0)
        self.view_notas.alignment_loaded.connect(self._on_alignment_loaded)
        self.view_notas.onset_dragged.connect(self.view_prepro._on_onset_dragged)   # onset manual en la ventana de notas
        self.view_notas.log.connect(self._append_log)
        self.view_notas.log.connect(self._on_notas_log)

        self.view_dir.log.connect(self._append_log)

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

    def _on_alignment_loaded(self, takes, tdoa):
        if takes:
            self.ribbon.mark_done('align_takes', "desde la máscara")
        if tdoa:
            self.ribbon.mark_done('align_ref', "desde la máscara")

    def _ask_mask(self):
        """Antes de abrir Segmentación por notas: si hay audio y todavía no hay segmentos, ofrece cargar una
        máscara guardada (trae la alineación de los pasos 1 y 2 y los segmentos). Se pregunta una vez por audio."""
        if self._ma is None or getattr(self, '_mask_asked', False) or self.view_notas._segs is not None:
            return
        self._mask_asked = True
        box = QMessageBox(self)
        box.setWindowTitle("Segmentación por notas")
        box.setText("¿Tenés una máscara guardada?")
        box.setInformativeText("Si la cargás se reaplican la alineación entre tomas y el TDOA y se recuperan los "
                               "segmentos, sin recalcular.")
        b_load = box.addButton("Cargar máscara…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("No, continuar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_load:
            self._on_load_mask()

    def _show_notas_dialog(self):
        """Herramientas ▸ Segmentación por notas…: el flujo de Notas (alinear, escala, detección y editor F0)
        en una ventana no modal. El widget se arma una sola vez y se reutiliza."""
        if not (getattr(self, '_notas_dlg', None) is not None and self._notas_dlg.isVisible()):
            self._ask_mask()
        dlg = getattr(self, '_notas_dlg', None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Segmentación por notas")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.addWidget(self.view_notas)
            dlg.resize(1280, 720)
            self._notas_dlg = dlg
        dlg.setModal(False)          # no bloquea la ventana principal: se puede seguir usando Procesamiento
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _open_graph_options(self, kind: str):
        """Opciones ▸ Gráficos ▸ …: el mismo modal de Propiedades del gráfico (o el de Imágenes).
        'smoothing' (Herramientas ▸ Suavizado…) es aparte: una sola configuración común a Polar 2D,
        Superficie 3D y Esfera, no un modal de Propiedades de un gráfico en particular."""
        if kind == "notas":
            self._show_notas_dialog()
            return
        if kind == "images":
            from ui.options_dialogs import ImageOptionsDialog
            ImageOptionsDialog(self).exec()
            return
        if kind == "smoothing":
            from ui.options_dialogs import SmoothingOptionsDialog
            dlg = SmoothingOptionsDialog(self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self.view_dir.apply_smoothing_settings(dlg.values())
            return
        self.ribbon._switch_tab(1)          # Directividad
        self.view_dir._show_properties_panel(kind)

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
            self.view_dir.source_file = path
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
            self.ribbon._b.emitPlotParams()          # aplica la vista activa (matriz por defecto)
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

    def _correct_gain(self, pairs):
        """Corregir ganancia (matriz radial): iguala el nivel de las celdas elegidas al de su simétrica,
        modificando los WAV de la carpeta de audios (con respaldo de los originales)."""
        plan = self.view_dir.plan_gain_correction(pairs)
        if isinstance(plan, str):
            return plan
        gains = [g for _p, _i, _j, g in plan["items"]]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Corregir ganancia")
        box.setText(f"Se van a modificar {len(gains)} archivos WAV de la carpeta de audios.")
        box.setInformativeText(
            f"Cada uno se iguala al nivel de su simétrico (entre {min(gains):+.1f} y {max(gains):+.1f} dB).\n\n"
            f"Antes de tocarlos se copian los originales a:\n{plan['backup']}\n\n"
            "Si sale mal, Ctrl+Z en la matriz lo deshace (mientras no cierres el programa); después queda solo la "
            "copia de esa carpeta.")
        b_ok = box.addButton("Corregir y guardar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not b_ok:
            return "Corrección cancelada."
        msg = self.view_dir.execute_gain_correction(plan)
        self._append_log(f"[Ganancia] {msg}")
        self._refresh_matrix()
        self.ribbon._b.emitPlotParams()
        return msg

    def _apply_mirror_replacements(self, pairs):
        """Aplica los reemplazos de la matriz al audio y vuelve a dibujar la señal en el tiempo."""
        msg = self.view_dir.apply_mirror_replacements(pairs)
        self.ribbon._b.emitPlotParams()          # redibuja Procesamiento con los datos ya reemplazados
        self._refresh_matrix()
        return msg

    def _undo_replacement(self):
        msg = self.view_dir.undo_replacements()
        self.ribbon._b.emitPlotParams()
        self._refresh_matrix()
        return msg

    def _refresh_matrix(self):
        """Pone al día el panel de la matriz radial (si existe) con los datos actuales."""
        if self.ribbon._b.state.get('matrix') and self._matrix_win is None:
            self.ribbon._b.emitPlotParams()                  # hay datos nuevos: la matriz aparece por defecto
            return
        win = self._matrix_win
        if win is None:
            return
        m = self.view_dir.matrix_bands()
        if m is not None:
            levels, az, th, freqs, src, unit = m
            win.refresh(levels, az, th, freqs, source=src, unit=unit, corr=self.view_dir.corr_delta_2d(),
                        onaxis=self.view_dir.onaxis_ref_1d())

    def _corr_offset_db(self):
        """Corrección por toma en dB por azimut (banda elegida), si está activada en el panel izquierdo."""
        ma = self.view_dir._get_current_ma()
        glob = getattr(ma, 'dir_delta_global', None)   # dB vs tiempo es banda ancha: corrección global
        return None if glob is None else np.asarray(glob)

    def _on_save_grid(self):
        """Guardar grilla (.gcclp): la grilla de 10° ya procesada, sin interpolar ni suavizar."""
        from core.grid_file import save_grid, EXT
        snap = self.view_dir.grid_snapshot()
        if snap is None:
            self._append_log("[Grilla] No hay grilla procesada para guardar.")
            return
        start = str(self._settings.value("last_grid_dir", "")) + "/grilla" + EXT
        path, _ = QFileDialog.getSaveFileName(self, "Guardar grilla", start, "Grilla procesada (*.gcclp)")
        if not path:
            return
        if not path.endswith(EXT):
            path += EXT
        st = self.ribbon._b.state
        meta = {"corr_ref": st.get('corr_ref', 'ref'), "corr_base": st.get('corr_base', 0),
                "view": self.view_dir.get_view_config()}   # estilos de los gráficos (como el .cclp)
        save_grid(path, snap['levels'], snap['azimuths'], snap['thetas'], snap['freqs'], snap['unit'], meta,
                  ref_raw=snap['ref_raw'], ref_eq=snap['ref_eq'])
        self._settings.setValue("last_grid_dir", str(Path(path).parent))
        self._append_log(f"[Grilla] Guardada → {path}")

    def _on_load_grid(self):
        """Abrir grilla (.gcclp): muestra la grilla guardada en la matriz y los gráficos."""
        from core.grid_file import load_grid
        path, _ = QFileDialog.getOpenFileName(self, "Abrir grilla", str(self._settings.value("last_grid_dir", "")),
                                              "Grilla procesada (*.gcclp)")
        if not path:
            return
        d = load_grid(path)
        self.ribbon._b.state.update({k: v for k, v in d['meta'].items() if k in ('corr_ref', 'corr_base')})
        self.view_dir.load_grid_snapshot(d)
        if d['meta'].get('view'):
            self.view_dir.apply_view_config(d['meta']['view'])   # estilos guardados en la grilla
        self._settings.setValue("last_grid_dir", str(Path(path).parent))
        self._append_log(f"[Grilla] Abierta: {Path(path).name}")

    def _on_matrix_grid(self):
        """Cambió la interpolación o el suavizado: matriz y gráficos se actualizan."""
        self._refresh_matrix()
        self.view_dir.show_graphs()

    def _on_nivelar_onaxis(self):
        """Nivelar a on-axis (paso 3): sobre la grilla corregida por toma."""
        if not self.view_dir.nivelar_onaxis():
            self._append_log("[On-axis] Primero aplicá la corrección por toma (Aplicar).")
            return
        self._append_log("[On-axis] Grilla nivelada: 0 dB en giro 0°, θ 0° para cada banda.")
        self.ribbon.mark_done('onaxis', "0 dB en giro 0°, θ 0° para cada banda")

    def _on_filter_bands(self):
        """Filtrar por bandas (1/3): calcula el Leq por posición y banda desde los audios cargados."""
        if not self.view_dir.filter_bands():
            self._append_log("[Filtrar] No hay audio cargado.")

    def _on_corr_recalc(self):
        """Corrección por toma (Aplicar): sólo recalcula la diferencia de niveles entre tomas
        con el mic de referencia y la toma base elegidos. No relee audio ni recalcula todo.
        Al terminar, loguea qué cambió (tomas y posiciones de la matriz) y cuánto."""
        st = self.ribbon._b.state
        ref = str(st.get('corr_ref', 'ref'))
        self.view_dir.corr_ref_th = 'ref' if ref == 'ref' else int(float(ref))
        ref_az = int(float(st.get('corr_base', 0)))   # clave propia: no la pisa 'Ref. azimut' de Parámetros
        ma = self.view_dir._get_current_ma()
        before_lv = None if ma is None or ma.dir_levels is None else ma.dir_levels.copy()
        before_d  = None if ma is None or getattr(ma, 'dir_delta_global', None) is None else np.array(ma.dir_delta_global)
        if not self.view_dir.apply_take_correction(ref_az):
            self._append_log("[Corrección] No hay audio cargado para calcular la corrección.")
            return
        self._append_log(f"[Corrección] Mic {ref}, toma base {ref_az}°.")
        self.ribbon.mark_done('corr', f"mic {ref}, toma base {ref_az}°")
        self._log_corr_diff(ma, before_lv, before_d)
        self.ribbon._b.emitPlotParams()   # redibuja dB vs tiempo con el nuevo desplazamiento

    def _log_corr_diff(self, ma, before_lv, before_d):
        """Resumen de lo que cambió con Aplicar: corrección por toma (dB, banda ancha) y las
        posiciones de la matriz con mayor cambio (giro, θ, dB)."""
        if ma is None or before_lv is None or ma.dir_levels is None:
            return
        after_d = np.asarray(ma.dir_delta_global)
        self._append_log("[Corrección] Cambio por toma (dB, banda ancha):")
        for i_az, az in enumerate(ma.angles):
            b = 0.0 if before_d is None else float(before_d[i_az])
            self._append_log(f"    giro {az:>3}°: {b:+6.2f} → {float(after_d[i_az]):+6.2f}   (Δ {float(after_d[i_az]) - b:+6.2f})")
        bi = min(self.view_dir._current_band_idx, ma.dir_levels.shape[2] - 1)
        diff = ma.dir_levels[:, :, bi] - before_lv[:, :, bi]
        changed = np.argwhere(np.abs(diff) > 0.05)
        self._append_log(f"[Corrección] Posiciones con cambio > 0.05 dB (banda {bi}): {len(changed)} de {diff.size}. "
                         f"Máximo |Δ| = {np.nanmax(np.abs(diff)):.2f} dB")
        order = sorted(changed.tolist(), key=lambda ij: -abs(diff[ij[0], ij[1]]))[:8]
        for i_az, i_th in order:
            th = ma.thetas[i_th]
            self._append_log(f"    giro {ma.angles[i_az]:>3}°, θ {th}: {float(diff[i_az, i_th]):+6.2f} dB")

    def _on_view_choice(self, key):
        """Desplegable de Procesamiento (arriba a la derecha): cambia la misma vista que el menú Vista."""
        st = self.ribbon._b.state
        st.update(matrix=key == 'matrix', db=key == 'db', envelope=key in ('db', 'envelope'), detect=False)
        self.ribbon._b.emitPlotParams()

    def _on_plot_params(self, theta, azimuth, env, db, yrange, smoothing):
        st = self.ribbon._b.state
        key = ('matrix' if st.get('matrix') else 'db' if db else 'envelope' if env else 'amp')
        self.view_prepro.set_view_choice(key)
        self.view_notas.set_signal_view(yrange, smoothing)     # señal dB de Segmentación por notas
        if st.get('matrix'):              # Vista ▸ Matriz radial (por defecto)
            panel = self._ensure_matrix_panel()
            if panel is not None:
                self.view_prepro.show_matrix(panel)
                return
            self.view_prepro.show_waveform()                # sin datos todavía: muestra la señal, sin cambiar la preferencia
            self.view_prepro.refresh_plot(theta, azimuth, env, db, yrange, smoothing)
            return
        self.view_prepro.show_waveform()
        self.view_prepro.refresh_plot(theta, azimuth, env, db, yrange, smoothing)

    def _ensure_matrix_panel(self):
        """Crea (la primera vez) o pone al día el panel de la matriz radial en Procesamiento."""
        from ui.matrix_dialog import MatrixPanel
        m = self.view_dir.matrix_bands()
        if m is None:                       # sin datos: esqueleto en blanco (se llena al cargar o calcular)
            import numpy as np
            ang = np.arange(0, 181, 10.0)
            m = (np.full((len(ang), len(ang), 1), np.nan), ang, ang, [None], None, 'sin datos')
        levels, az, th, freqs, src, unit = m
        if self._matrix_win is None:
            self._matrix_win = MatrixPanel(levels, az, th, freqs, source=src, on_click=self.view_dir.play_cell,
                                           apply_cb=self._apply_mirror_replacements, gain_cb=self._correct_gain,
                                           undo_cb=self._undo_replacement, unit=unit,
                                           corr=self.view_dir.corr_delta_2d(), onaxis=self.view_dir.onaxis_ref_1d())
            self.view_dir.on_data_changed = self._refresh_matrix
        else:
            self._matrix_win.refresh(levels, az, th, freqs, source=src, unit=unit,
                                     corr=self.view_dir.corr_delta_2d(), onaxis=self.view_dir.onaxis_ref_1d())
        return self._matrix_win

    def _on_apply_hpf(self, hz: float):
        self.view_prepro.apply_hpf(hz)

    def _on_align_takes(self, onset, thresh, theta, window_ms):
        self.view_prepro.align_takes(onset, thresh, theta, window_ms)

    def _on_align_preview(self, onset, thresh, theta):
        self.view_prepro.set_align_params(onset, thresh, theta)
        self.view_notas.set_align_params(onset, thresh, theta)

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
            self.ribbon.mark_done('calibrar', "convertido a dB SPL")

        dlg.ma_updated.connect(applied)
        dlg.log.connect(self._append_log)
        dlg.exec()

    # ── Slots de Notas ────────────────────────────────────────────────────────

    def _on_detect_notes(self, tol, purity, start_s, grad, ref_theta):
        self.view_notas.detect_notes(tol, purity, start_s, grad, ref_theta)

    def _on_notas_log(self, msg: str):
        if "Detección completada" in msg or "Máscara cargada" in msg:
            self.view_notas.btn_extract.setEnabled(True)
            self.ribbon._act['save_mask'].setEnabled(True)
            if "Detección completada" in msg:
                self.ribbon.mark_done('detect', "notas detectadas")
                self.view_notas.show_f0()          # el resultado de la detección se ve en la pestaña F0

    def _on_edit_scale(self):
        dlg = ScaleEditorDialog(self.view_notas.get_scale(), self.ribbon.current_scale_name(), self)
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

    # ── Slots de Directividad ─────────────────────────────────────────────────

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
        nota = params.get('nota')
        if nota != getattr(self, '_last_nota', nota):
            self._refresh_matrix()                 # otra muestra: la matriz radial muestra esa nota
        self._last_nota = nota

    def _on_intersect_cut3d(self):
        """"Intersectar" (barra izquierda, grupo "Corte (Superficie 3D)"): muestra el plano de
        referencia y la curva real a esa elevación sobre la Superficie 3D — sólo esa vista,
        nunca toca Polar 2D (queda totalmente independiente)."""
        sec = self.view_dir._sections.get('3d')
        if sec is None:
            return
        elevation = float(self.ribbon._b.state.get('cut3d_elevation', 0.0))
        sec._style['cut_visible']   = True
        sec._style['cut_elevation'] = elevation
        sec.view.set_style(sec._style)

    def _on_ma_ready(self, ma):
        self._ma = ma
        self._refresh_matrix()
        # Escala Y por defecto de las señales dB: sin calibrar −60…0 dB, calibrada 40…100 dB.
        # Sólo se cambia cuando cambia el estado de calibración (no pisa lo que el usuario escribió).
        cal = ma.calibration is not None
        if cal != getattr(self, '_last_cal', None):
            self._last_cal = cal
            self.ribbon._b.state['ymin'], self.ribbon._b.state['ymax'] = (40.0, 100.0) if cal else (-60.0, 0.0)
            for load in self.ribbon._loaders:
                load()
        shape = ma.tensor.shape
        self.statusBar().showMessage(
            f"Tensor {shape}  ·  sr {ma.sr} Hz  ·  "
            f"Cal: {'OK' if ma.calibration is not None else '—'}  ·  "
            f"SPL: {'OK' if ma._is_spl else '—'}"
        )
        # Primero inyectar ma en las vistas para que estén listas
        # antes de que ribbon dispare _emit_plot_params()
        self.view_prepro.set_ma(ma)
        # Deferido: set_ma dispara un cómputo F0 en un Worker thread que, si arranca
        # en medio de la reconstrucción pesada de la matriz/vista 3D de más abajo,
        # cuelga el proceso entero (crash nativo sin traceback). Un tick después ya
        # terminó esa reconstrucción y no compiten por CPU/GL al mismo tiempo.
        QTimer.singleShot(0, lambda: self.view_notas.set_ma(ma))
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
        # A la izquierda, apilado debajo del dock de Parámetros (misma columna, mismo ancho).
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._log_dock)
        self.splitDockWidget(self._params_dock, self._log_dock, Qt.Orientation.Vertical)
        self.ribbon.add_view_action(self._log_dock.toggleViewAction())
        self._log_dock.visibilityChanged.connect(
            lambda vis: vis and QTimer.singleShot(0, self._size_log_dock))

        # ajustar restricciones de tamaño según dónde está anclado
        self._log_dock.dockLocationChanged.connect(self._on_log_dock_location)
        self._log_dock.topLevelChanged.connect(self._on_log_floating)

        # visible por defecto, abajo a la izquierda; se puede ocultar desde Ver ▸ Log

    def _size_log_dock(self):
        """Al abrir el Log: ocupa ~44% del alto de la columna izquierda, debajo de Parámetros (que se queda con el resto)."""
        if self._log_dock.isFloating() or self.dockWidgetArea(self._log_dock) != Qt.DockWidgetArea.LeftDockWidgetArea:
            return
        total = self._params_dock.height() + self._log_dock.height()
        log_h = max(180, int(total * 0.44))
        self.resizeDocks([self._params_dock, self._log_dock], [total - log_h, log_h], Qt.Orientation.Vertical)

    def _on_log_dock_location(self, area):
        _MAX = 16_777_215
        sides = (Qt.DockWidgetArea.LeftDockWidgetArea,
                 Qt.DockWidgetArea.RightDockWidgetArea)
        if area in sides:
            self._log_dock.setMaximumHeight(_MAX)
            self._log_dock.setMaximumWidth(_MAX)   # el ancho lo fija la columna de Parámetros
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
        # Un hilo de trabajo (Worker/QThread) todavía corriendo hace que Python no termine al cerrar:
        # se le pide que pare y se espera un momento antes de salir.
        try:
            from core.worker import stop_all_workers
            stop_all_workers()
        except Exception as exc:       # que un error al parar hilos no impida cerrar la ventana
            print(f"[cierre] no se pudieron detener los hilos: {exc}")
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
