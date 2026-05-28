# -*- coding: utf-8 -*-
"""
PantallaCarga: pantalla de configuración y procesamiento.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox,
    QComboBox, QTextEdit, QProgressBar, QFileDialog,
    QGroupBox, QCheckBox,
)

from ..config import (
    DEFAULT_N_MICS, DEFAULT_ANG_INICIO, DEFAULT_ANG_FIN, DEFAULT_PASO_MESA,
    DEFAULT_TEMPLATE_MICS, DEFAULT_TEMPLATE_REFS,
    DEFAULT_FC_HZ, DEFAULT_MARGEN_DB, DEFAULT_ROLLON_MS,
    DEFAULT_ROLLOFF_MS, DEFAULT_FRAME_MS, DEFAULT_CALIBRACION_DB,
)
from ..preprocesador import Preprocesador
from ..sesion import Sesion


class PantallaCarga(QWidget):
    """
    Pantalla de carga.

    El usuario elige UNA carpeta (la carpeta Media de Reaper) que contiene
    todos los WAVs de todas las dinámicas mezclados. El app los clasifica
    por el nombre de archivo.

    Signals
    -------
    sesion_lista(str, Sesion)  : dinámica, sesión cargada/procesada
    """

    sesion_lista = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preprocesadores: dict[str, Preprocesador] = {}
        self._sesiones: dict[str, Sesion] = {}
        self._construir_ui()

    # ══════════════════════════════════════════════════════════════
    # Construcción de UI
    # ══════════════════════════════════════════════════════════════

    def _construir_ui(self):
        root = QHBoxLayout(self)
        root.setSpacing(12)

        izq = QVBoxLayout()
        izq.setSpacing(8)
        izq.addWidget(self._grupo_rutas())
        izq.addWidget(self._grupo_nomenclatura())
        izq.addWidget(self._grupo_array())
        izq.addWidget(self._grupo_preprocesamiento())
        izq.addStretch()
        izq.addWidget(self._grupo_acciones())

        der = QVBoxLayout()
        der.setSpacing(8)
        der.addWidget(self._grupo_progreso())
        der.addWidget(self._grupo_log(), stretch=1)

        root.addLayout(izq, stretch=2)
        root.addLayout(der, stretch=3)

    def _grupo_rutas(self) -> QGroupBox:
        gb = QGroupBox("Carpeta de mediciones (Media de Reaper)")
        lay = QGridLayout(gb)

        self._campo_media = QLineEdit()
        self._campo_media.setPlaceholderText("Carpeta con todos los WAVs…")
        btn_media = QPushButton("…")
        btn_media.setFixedWidth(30)
        btn_media.clicked.connect(lambda: self._explorar(self._campo_media))
        self._campo_media.textChanged.connect(self._on_carpeta_cambiada)

        lay.addWidget(QLabel("Mediciones:"), 0, 0)
        lay.addWidget(self._campo_media,     0, 1)
        lay.addWidget(btn_media,             0, 2)

        info = QLabel(
            "Todos los WAVs (forte y piano) en una misma carpeta.\n"
            "La sesión procesada se guarda en una subcarpeta '_sesion'."
        )
        info.setStyleSheet("color: gray; font-size: 10px;")
        info.setWordWrap(True)
        lay.addWidget(info, 1, 0, 1, 3)
        return gb

    def _grupo_nomenclatura(self) -> QGroupBox:
        gb = QGroupBox("Plantillas de nombre de archivo")
        lay = QGridLayout(gb)

        self._campo_tmpl_mics = QLineEdit(DEFAULT_TEMPLATE_MICS)
        self._campo_tmpl_refs = QLineEdit(DEFAULT_TEMPLATE_REFS)

        lay.addWidget(QLabel("Micrófonos:"),  0, 0)
        lay.addWidget(self._campo_tmpl_mics,  0, 1)
        lay.addWidget(QLabel("Referencias:"), 1, 0)
        lay.addWidget(self._campo_tmpl_refs,  1, 1)

        info = QLabel("Marcadores disponibles: {MIC}  {DIN}  {ANG}")
        info.setStyleSheet("color: gray; font-size: 10px;")
        lay.addWidget(info, 2, 0, 1, 2)
        return gb

    def _grupo_array(self) -> QGroupBox:
        gb = QGroupBox("Configuración del array")
        lay = QGridLayout(gb)

        self._spin_n_mics  = QSpinBox(); self._spin_n_mics.setRange(1, 64)
        self._spin_n_mics.setValue(DEFAULT_N_MICS)
        self._spin_ang_ini = QSpinBox(); self._spin_ang_ini.setRange(0, 360)
        self._spin_ang_ini.setValue(DEFAULT_ANG_INICIO)
        self._spin_ang_fin = QSpinBox(); self._spin_ang_fin.setRange(0, 360)
        self._spin_ang_fin.setValue(DEFAULT_ANG_FIN)
        self._spin_paso    = QSpinBox(); self._spin_paso.setRange(1, 90)
        self._spin_paso.setValue(DEFAULT_PASO_MESA)

        lay.addWidget(QLabel("N° micrófonos:"),     0, 0)
        lay.addWidget(self._spin_n_mics,             0, 1)
        lay.addWidget(QLabel("Ángulo inicio (°):"), 1, 0)
        lay.addWidget(self._spin_ang_ini,            1, 1)
        lay.addWidget(QLabel("Ángulo fin (°):"),    2, 0)
        lay.addWidget(self._spin_ang_fin,            2, 1)
        lay.addWidget(QLabel("Paso mesa (°):"),     3, 0)
        lay.addWidget(self._spin_paso,               3, 1)
        return gb

    def _grupo_preprocesamiento(self) -> QGroupBox:
        gb = QGroupBox("Parámetros de preprocesamiento")
        lay = QGridLayout(gb)

        self._spin_fc = QDoubleSpinBox()
        self._spin_fc.setRange(10, 1000); self._spin_fc.setValue(DEFAULT_FC_HZ)
        self._spin_fc.setSuffix(" Hz")

        self._spin_margen = QDoubleSpinBox()
        self._spin_margen.setRange(3, 40); self._spin_margen.setValue(DEFAULT_MARGEN_DB)
        self._spin_margen.setSuffix(" dB")

        self._spin_rollon = QSpinBox()
        self._spin_rollon.setRange(0, 2000); self._spin_rollon.setValue(int(DEFAULT_ROLLON_MS))
        self._spin_rollon.setSuffix(" ms")

        self._spin_rolloff = QSpinBox()
        self._spin_rolloff.setRange(0, 2000); self._spin_rolloff.setValue(int(DEFAULT_ROLLOFF_MS))
        self._spin_rolloff.setSuffix(" ms")

        self._combo_frame = QComboBox()
        for ms in [10, 20, 30, 50]:
            self._combo_frame.addItem(f"{ms} ms", ms)

        self._spin_calibracion = QDoubleSpinBox()
        self._spin_calibracion.setRange(0, 150)
        self._spin_calibracion.setDecimals(1)
        self._spin_calibracion.setValue(DEFAULT_CALIBRACION_DB)
        self._spin_calibracion.setSuffix(" dB")
        self._spin_calibracion.setToolTip(
            "Offset de calibración: dBSPL − dBFS\n"
            "Ej.: 94 dBSPL @ −3 dBFS  →  offset = 97 dB"
        )

        lay.addWidget(QLabel("fc filtro pasa altos:"), 0, 0)
        lay.addWidget(self._spin_fc,                   0, 1)
        lay.addWidget(QLabel("Umbral onset:"),         1, 0)
        lay.addWidget(self._spin_margen,               1, 1)
        lay.addWidget(QLabel("Roll-on:"),              2, 0)
        lay.addWidget(self._spin_rollon,               2, 1)
        lay.addWidget(QLabel("Roll-off:"),             3, 0)
        lay.addWidget(self._spin_rolloff,              3, 1)
        lay.addWidget(QLabel("Frame STFT:"),           4, 0)
        lay.addWidget(self._combo_frame,               4, 1)
        lay.addWidget(QLabel("Calibración SPL:"),      5, 0)
        lay.addWidget(self._spin_calibracion,          5, 1)
        return gb

    def _grupo_acciones(self) -> QGroupBox:
        gb = QGroupBox("Acciones")
        lay = QVBoxLayout(gb)

        # Selector de qué dinámicas procesar
        hd = QHBoxLayout()
        self._chk_forte = QCheckBox("forte")
        self._chk_piano = QCheckBox("piano")
        self._chk_forte.setChecked(True)
        self._chk_piano.setChecked(True)
        hd.addWidget(QLabel("Procesar:"))
        hd.addWidget(self._chk_forte)
        hd.addWidget(self._chk_piano)
        hd.addStretch()
        lay.addLayout(hd)

        self._chk_guardar_proc = QCheckBox("Guardar audio procesado en _procesados/")
        self._chk_guardar_proc.setToolTip(
            "Guarda los WAVs filtrados, alineados y recortados\n"
            "en <carpeta>/_procesados/<dinámica>/ para verificar el preprocesamiento."
        )
        lay.addWidget(self._chk_guardar_proc)

        hb = QHBoxLayout()
        self._btn_procesar = QPushButton("▶  Procesar")
        self._btn_cargar   = QPushButton("Cargar sesión anterior")
        self._btn_procesar.setMinimumHeight(36)
        self._btn_cargar.setMinimumHeight(36)
        self._btn_procesar.clicked.connect(self._on_procesar)
        self._btn_cargar.clicked.connect(self._on_cargar_sesion)
        hb.addWidget(self._btn_procesar)
        hb.addWidget(self._btn_cargar)
        lay.addLayout(hb)
        return gb

    def _grupo_progreso(self) -> QGroupBox:
        gb = QGroupBox("Progreso")
        lay = QVBoxLayout(gb)
        self._barra = QProgressBar()
        self._barra.setRange(0, 100)
        self._lbl_estado = QLabel("Listo.")
        self._lbl_estado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._barra)
        lay.addWidget(self._lbl_estado)
        return gb

    def _grupo_log(self) -> QGroupBox:
        gb = QGroupBox("Log")
        lay = QVBoxLayout(gb)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(_fuente_mono())
        lay.addWidget(self._log)
        return gb

    # ══════════════════════════════════════════════════════════════
    # Lógica
    # ══════════════════════════════════════════════════════════════

    def _explorar(self, campo: QLineEdit):
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if ruta:
            campo.setText(ruta)

    def _on_carpeta_cambiada(self, texto: str):
        """Cuando el usuario cambia la carpeta, habilita 'Cargar sesión' si existe."""
        carpeta_sesion = self._carpeta_sesion(texto)
        tiene_sesion = any(
            Sesion.existe(carpeta_sesion, din) for din in ["forte", "piano"]
        )
        self._btn_cargar.setEnabled(tiene_sesion)

    def _carpeta_media(self) -> Path:
        return Path(self._campo_media.text().strip())

    def _carpeta_sesion(self, carpeta_media: str | None = None) -> Path:
        base = Path(carpeta_media or self._campo_media.text().strip())
        return base / "_sesion"

    def _angulos(self) -> list[int]:
        ini  = self._spin_ang_ini.value()
        fin  = self._spin_ang_fin.value()
        paso = self._spin_paso.value()
        return list(range(ini, fin + 1, paso))

    def _on_procesar(self):
        carpeta = self._carpeta_media()
        if not carpeta.exists():
            self._agregar_log("[ERROR] La carpeta de mediciones no existe.")
            return

        dinamicas = []
        if self._chk_forte.isChecked(): dinamicas.append("forte")
        if self._chk_piano.isChecked(): dinamicas.append("piano")
        if not dinamicas:
            self._agregar_log("[ERROR] Seleccioná al menos una dinámica.")
            return

        for din in dinamicas:
            self._procesar_dinamica(din, str(carpeta))

    def _procesar_dinamica(self, dinamica: str, carpeta: str):
        if dinamica in self._preprocesadores:
            self._preprocesadores[dinamica].cancelar()

        prep = Preprocesador(self)
        prep.progreso.connect(self._barra.setValue)
        prep.log.connect(self._agregar_log)
        prep.terminado.connect(lambda s, d=dinamica: self._on_terminado(d, s))
        prep.error.connect(lambda e, d=dinamica: self._on_error(d, e))

        self._preprocesadores[dinamica] = prep
        self._btn_procesar.setEnabled(False)
        self._lbl_estado.setText(f"Procesando {dinamica}…")

        prep.iniciar(
            carpeta             = carpeta,
            dinamica            = dinamica,
            template_mics       = self._campo_tmpl_mics.text(),
            template_refs       = self._campo_tmpl_refs.text(),
            n_mics              = self._spin_n_mics.value(),
            angulos_array       = self._angulos(),
            angulos_mesa        = self._angulos(),
            carpeta_sesion      = str(self._carpeta_sesion()),
            fc_hz               = self._spin_fc.value(),
            margen_db           = self._spin_margen.value(),
            rollon_ms           = float(self._spin_rollon.value()),
            rolloff_ms          = float(self._spin_rolloff.value()),
            frame_ms            = float(self._combo_frame.currentData()),
            calibracion_db      = self._spin_calibracion.value(),
            guardar_procesados  = self._chk_guardar_proc.isChecked(),
        )

    def _on_terminado(self, dinamica: str, sesion):
        self._sesiones[dinamica] = sesion
        self._agregar_log(f"[OK] Sesión '{dinamica}' lista.")
        self._btn_procesar.setEnabled(True)
        self._lbl_estado.setText("Listo.")
        self.sesion_lista.emit(dinamica, sesion)

    def _on_error(self, dinamica: str, msg: str):
        self._agregar_log(f"[ERROR {dinamica}] {msg}")
        self._btn_procesar.setEnabled(True)
        self._lbl_estado.setText("Error.")

    def _on_cargar_sesion(self):
        carpeta = self._carpeta_sesion()
        cargadas = 0
        for din in ["forte", "piano"]:
            if Sesion.existe(carpeta, din):
                try:
                    sesion = Sesion.cargar(carpeta, din)
                    self._sesiones[din] = sesion
                    self._agregar_log(f"[OK] Sesión '{din}' cargada.")
                    self.sesion_lista.emit(din, sesion)
                    cargadas += 1
                except Exception as e:
                    self._agregar_log(f"[ERROR] No se pudo cargar '{din}': {e}")
        if cargadas == 0:
            self._agregar_log("[INFO] No se encontró ninguna sesión guardada.")

    def _agregar_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f"[{ts}] {msg}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )


def _fuente_mono():
    from PyQt6.QtGui import QFont
    f = QFont("Consolas", 9)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f
