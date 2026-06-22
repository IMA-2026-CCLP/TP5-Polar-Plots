"""
ui/main_window.py — Ventana principal con Ribbon global + QStackedWidget.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget,
    QDockWidget, QTextEdit, QDialog, QDialogButtonBox,
    QFileDialog, QToolButton, QApplication,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QTextCursor

from core.worker import Worker

from ui.styles               import QSS, get_qss
from ui.ribbon               import RibbonBar
from ui                      import theme as _theme
from ui.tab_carga            import TabCarga
from ui.tab_preprocesamiento import TabPreprocesamiento
from ui.tab_calibracion      import TabCalibracion
from ui.tab_notas            import TabNotas, ScaleEditorDialog
from ui.tab_directividad     import TabDirectividad
from core.data_store         import load_results, save_results


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Polar Pattern CCLP")
        self.setMinimumSize(1200, 750)
        self.resize(1440, 860)
        self.setStyleSheet(QSS)

        self._ma       = None
        self._settings = QSettings("AcousticTools", "PolarAnalyzerV2")

        self._build_ui()
        self._connect_ribbon()
        self._restore_geometry()

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # Vistas de contenido
        self.view_archivo    = TabCarga()
        self.view_prepro     = TabPreprocesamiento()
        self.view_notas      = TabNotas()
        self.view_dir        = TabDirectividad()

        # Ribbon
        self.ribbon = RibbonBar()

        # Stack de contenido
        self._stack = QStackedWidget()
        self._stack.addWidget(self.view_archivo)    # 0
        self._stack.addWidget(self.view_prepro)     # 1
        self._stack.addWidget(self.view_notas)      # 2
        self._stack.addWidget(self.view_dir)        # 3
        self._stack.setCurrentIndex(3)              # Directividad por defecto

        # Layout central
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.ribbon)
        lay.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._setup_log_dock()

        self._update_statusbar_style(_theme.current())
        self.statusBar().showMessage("Listo.")

    # ── Conexiones ────────────────────────────────────────────────────────────

    def _connect_ribbon(self):
        rb = self.ribbon

        # Navegación
        rb.tab_changed.connect(self._on_tab_changed)
        # Iniciar en Directividad
        rb._tab_grp.button(3).setChecked(True)
        rb._stack.setCurrentIndex(3)

        # ── Archivo
        rb.sig_load_audio.connect(lambda: self._show_archivo_mode('audio'))
        rb.sig_load_tensor.connect(lambda: self._show_archivo_mode('tensor'))
        rb.sig_save_tensor.connect(self.view_archivo._on_guardar_npz)
        rb.sig_load_polar_npz.connect(self._on_load_polar_npz)
        rb.sig_save_polar_npz.connect(self._on_save_polar_npz)

        # ── Procesamiento
        rb.sig_plot_params.connect(self._on_plot_params)
        rb.sig_apply_hpf.connect(self._on_apply_hpf)
        rb.sig_align_takes.connect(self._on_align_takes)
        rb.sig_align_preview.connect(self._on_align_preview)
        rb.sig_align_ref.connect(self._on_align_ref)
        rb.sig_open_calibracion.connect(self._open_calibracion_dialog)
        rb.sig_to_spl.connect(self._on_to_spl)

        # ── Notas
        rb.sig_detect_notes.connect(self._on_detect_notes)
        rb.sig_edit_scale.connect(self._on_edit_scale)
        rb.sig_preset_changed.connect(self.view_notas._set_scale_from_preset)
        rb.sig_save_mask.connect(self._on_save_mask)
        rb.sig_load_mask.connect(self._on_load_mask)

        # ── Directividad
        rb.sig_compute_dir.connect(self._on_compute_dir)
        rb.sig_save_dir_npz.connect(self._on_save_dir_npz)
        rb.sig_dir_display_changed.connect(self._on_dir_display_changed)

        # ── Tema
        rb.sig_theme_toggled.connect(self._toggle_theme)

        # ── Señales de retorno de las vistas
        self.view_archivo.ma_ready.connect(self._on_ma_ready)
        self.view_archivo.log.connect(self._append_log)

        self.view_prepro.ma_updated.connect(self._on_ma_ready)
        self.view_prepro.log.connect(self._append_log)

        self.view_notas.ma_updated.connect(self._on_ma_ready)
        self.view_notas.log.connect(self._append_log)
        self.view_notas.log.connect(self._on_notas_log)

        self.view_dir.log.connect(self._append_log)
        self.view_dir.computed.connect(self._on_dir_computed)

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        import plot.balloon as _balloon
        p = _theme.toggle()
        _balloon.set_theme(p)
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

    def _on_tab_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)

    def _show_archivo_mode(self, mode: str):
        self.ribbon._switch_tab(0)
        self.view_archivo.set_source_mode(mode)

    # ── Slots de Archivo ──────────────────────────────────────────────────────

    def _on_load_polar_npz(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar NPZ polar", "", "NPZ (*.npz)"
        )
        if not path:
            return
        try:
            data = load_results(path)
            # Cambiar a Directividad ANTES de cargar para que las secciones
            # sean visibles cuando _refresh_display() las actualice
            self.ribbon._switch_tab(3)
            self.view_dir.load_from_npz(data)
            self.ribbon.set_dir_computed(data['thetas'])
            self.ribbon.set_dir_status(
                f"NPZ cargado\n{data['dir_freqs'][0]:.0f}–{data['dir_freqs'][-1]:.0f} Hz"
            )
            self._append_log(f"[Directividad] NPZ cargado desde {path}")
        except Exception as e:
            self._append_log(f"[ERROR] Al cargar NPZ polar: {e}")

    def _on_save_polar_npz(self):
        if self._ma is None or self._ma.dir_levels is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar NPZ polar", "", "NPZ (*.npz)")
        if not path:
            return
        try:
            rb = self.ribbon
            save_results(
                filepath       = path,
                ma             = self._ma,
                bands          = rb.combo_bands.currentText(),
                ref_azimuth    = int(float(rb.le_ref_az.text() or 0)),
                ref_theta_plot = int(float(rb.le_ref_th.text() or 0)),
            )
            self._append_log(f"[Directividad] Guardado → {path}")
        except Exception as e:
            self._append_log(f"[ERROR] Al guardar NPZ polar: {e}")

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
        self.ribbon.btn_to_spl.setEnabled(False)

        def _run():
            self._ma.to_spl()
            return self._ma

        def _done(ma):
            self._on_ma_ready(ma)
            self._append_log("[Calibración] Tensor convertido a SPL (Pa).")

        def _err(msg):
            self.ribbon.btn_to_spl.setEnabled(True)
            self._append_log(f"[ERROR] to_spl:\n{msg}")

        self._spl_worker = Worker(_run)
        self._spl_worker.finished.connect(_done)
        self._spl_worker.error.connect(_err)
        self._spl_worker.log.connect(self._append_log)
        self._spl_worker.start()

    def _open_calibracion_dialog(self):
        if self._ma is None:
            return
        dlg = _CalibracionDialog(self._ma, self)
        dlg.ma_updated.connect(self._on_ma_ready)
        dlg.log.connect(self._append_log)
        dlg.exec()

    # ── Slots de Notas ────────────────────────────────────────────────────────

    def _on_detect_notes(self, tol, purity, start_s, grad, ref_theta):
        self.view_notas.detect_notes(tol, purity, start_s, grad, ref_theta)

    def _on_notas_log(self, msg: str):
        if "Detección completada" in msg or "Máscara cargada" in msg:
            self.ribbon.btn_save_mask.setEnabled(True)

    def _on_edit_scale(self):
        dlg = ScaleEditorDialog(self.view_notas.get_scale(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.view_notas.set_scale(dlg.get_scale())

    def _on_save_mask(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar máscara de segmentos", "", "Máscara (*.json)"
        )
        if path:
            self.view_notas.save_mask(path)

    def _on_load_mask(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar máscara de segmentos", "", "Máscara (*.json)"
        )
        if path:
            self.view_notas.load_mask(path)
            self.ribbon.btn_save_mask.setEnabled(True)

    # ── Slots de Directividad ─────────────────────────────────────────────────

    def _on_compute_dir(self, bands, hz_min, hz_max, ref_az, ref_th):
        self.view_dir.compute_all(bands, hz_min, hz_max, ref_az, ref_th)

    def _on_save_dir_npz(self):
        self._on_save_polar_npz()

    def _on_dir_display_changed(self):
        params = self.ribbon.get_dir_display_params()
        self.view_dir.apply_display_params(params)

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
        # altura inicial al estar en la parte inferior
        self.resizeDocks([self._log_dock], [150], Qt.Orientation.Vertical)

        # ajustar restricciones de tamaño según dónde está anclado
        self._log_dock.dockLocationChanged.connect(self._on_log_dock_location)
        self._log_dock.topLevelChanged.connect(self._on_log_floating)

        # botón toggle en la barra de estado
        self._btn_log = QToolButton()
        self._btn_log.setText("Log ▾")
        self._btn_log.setCheckable(True)
        self._btn_log.setChecked(True)
        self._btn_log.setToolTip("Mostrar / ocultar log")
        self._btn_log.clicked.connect(self._toggle_log)
        self._log_dock.visibilityChanged.connect(self._on_log_visibility)
        self.statusBar().addPermanentWidget(self._btn_log)

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

    def _toggle_log(self):
        self._log_dock.setVisible(not self._log_dock.isVisible())

    def _on_log_visibility(self, visible: bool):
        self._btn_log.setChecked(visible)
        self._btn_log.setText("Log ▾" if visible else "Log ▸")

    def _append_log(self, text: str):
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text + "\n")
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _restore_geometry(self):
        geom = self._settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)

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

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self._cal_widget, 1)
        lay.addWidget(btns)
