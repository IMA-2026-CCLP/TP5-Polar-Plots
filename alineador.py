# -*- coding: utf-8 -*-
"""
Alineador Temporal de Tomas Múltiples
======================================
Herramienta de pre-procesamiento para el Analizador de Directividad Vocal.

Alinea grabaciones multi-toma sincronizando el micrófono de referencia:
  1. Carga todos los WAVs de referencia de la carpeta de mediciones
  2. Aplica filtro Butterworth pasa altos para limpiar graves
  3. Detecta el onset (inicio de nota) en cada toma con umbral adaptivo
  4. Refina la alineación con GCC-PHAT (correlación cruzada de fase)
  5. Detecta el offset (fin de nota) en cada toma
  6. Calcula duración común = nota más larga entre todas las tomas
  7. Exporta TODOS los WAVs (refs + 19 mics) alineados y recortados
     — las tomas más cortas se rellenan con ceros al final

Uso: python alineador.py
"""

from __future__ import annotations
import sys
import re
import tempfile
import atexit
import numpy as np
from pathlib import Path
from typing import Optional

import soundfile as sf
from scipy.signal import butter, sosfiltfilt
from math import gcd
from scipy.signal import resample_poly

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QGroupBox,
    QTextEdit, QProgressBar, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QSlider, QCheckBox, QSizePolicy,
    QTabWidget, QDialog, QDialogButtonBox,
)
from PyQt6.QtGui import QFont, QColor

import pyqtgraph as pg

try:
    from qt_material import apply_stylesheet
    _QT_MATERIAL = True
except ImportError:
    _QT_MATERIAL = False

try:
    import sounddevice as sd
    _SD_OK = True
except Exception:
    _SD_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# Modelo de datos
# ══════════════════════════════════════════════════════════════════════════════

class TomaDatos:
    """Datos de una toma (un ángulo de mesa giratoria)."""

    def __init__(self, ang: int, path_ref: Path, paths_mics: dict[int, Path]):
        self.ang        = ang
        self.path_ref   = path_ref
        self.paths_mics = paths_mics          # {num_mic: Path}

        # Señal de referencia original (nunca modificada — usada para export y display)
        self.signal_ref_orig: np.ndarray | None = None
        # Señal de referencia de trabajo (filtrada) — usada solo para análisis DSP
        self.signal_ref: np.ndarray | None = None
        self.sr: int = 0

        # Resultados del análisis
        self.onset:         int = 0   # onset detectado en esta toma (solo informativo)
        self.lag:           int = 0   # lag GCC-PHAT respecto a la maestra (informativo)
        self.start_aligned: int = 0   # inicio definitivo del segmento a exportar
        self.offset:        int = 0   # muestra de offset en signal_ref (fin de nota)

    @property
    def start(self) -> int:
        """Muestra de inicio del segmento exportado."""
        return max(0, self.start_aligned)

    @property
    def note_duration(self) -> int:
        """Duración de la nota en muestras (offset - start)."""
        return max(0, self.offset - self.start)

    @property
    def available_after_start(self) -> int:
        """Muestras disponibles desde start hasta el fin del archivo."""
        if self.signal_ref is None:
            return 0
        return max(0, len(self.signal_ref) - self.start)


# ══════════════════════════════════════════════════════════════════════════════
# Motor de alineación (DSP puro, sin Qt)
# ══════════════════════════════════════════════════════════════════════════════

class MotorAlineacion:
    """
    Realiza toda la cadena de procesamiento DSP.
    No tiene dependencias de Qt — puede usarse en un hilo secundario.
    """

    def __init__(self):
        self.tomas: list[TomaDatos] = []
        self.duracion_comun: int = 0    # muestras de nota (sin pre-roll)
        self.preroll_comun:  int = 0    # muestras de pre-roll incluidas en el export
        self._master_idx: int = 0

    # ── Carga ────────────────────────────────────────────────────────────────

    def cargar(
        self,
        carpeta: Path,
        dinamica: str,
        template_mics: str = "mic_{MIC}_ang_{DIN}_{ANG}.wav",
        template_refs: str = "mic_ref_ang_{DIN}_{ANG}.wav",
        log_cb=None,
    ):
        self.tomas = []
        re_mics = _compilar_template(template_mics)
        re_refs = _compilar_template(template_refs)

        refs_map: dict[int, Path] = {}
        mics_map: dict[int, dict[int, Path]] = {}

        for wav in sorted(carpeta.glob("*.wav")):
            nombre = wav.name
            m = re_refs.match(nombre)
            if m and m.group("din").lower() == dinamica.lower():
                refs_map[int(m.group("ang"))] = wav
                continue
            m = re_mics.match(nombre)
            if m and m.group("din").lower() == dinamica.lower():
                ang = int(m.group("ang"))
                mic = int(m.group("mic"))
                mics_map.setdefault(ang, {})[mic] = wav

        _log(log_cb, f"  Referencias encontradas : {len(refs_map)}")
        _log(log_cb, f"  Ángulos con mics        : {len(mics_map)}")

        if not refs_map:
            raise RuntimeError("No se encontraron archivos de referencia.")

        for ang in sorted(refs_map):
            paths_mics = mics_map.get(ang, {})
            toma = TomaDatos(ang, refs_map[ang], paths_mics)
            sig, sr = sf.read(str(refs_map[ang]), dtype="float32")
            if sig.ndim > 1:
                sig = sig[:, 0]
            toma.signal_ref      = sig
            toma.signal_ref_orig = sig.copy()   # copia inmutable para export/display
            toma.sr = int(sr)
            self.tomas.append(toma)
            _log(log_cb, f"  Cargado {ang:>4}°  {len(sig)/sr:.2f} s  sr={sr} Hz")

        if not self.tomas:
            raise RuntimeError("No se cargaron tomas.")

    # ── Paso 1: Filtro pasa altos ─────────────────────────────────────────────

    def filtrar(self, fc_hz: float = 100.0, log_cb=None):
        _log(log_cb, f"  Butterworth HP orden 4  fc={fc_hz} Hz  (sosfiltfilt)")
        for toma in self.tomas:
            sos = butter(4, fc_hz / (toma.sr / 2), btype="high", output="sos")
            toma.signal_ref = sosfiltfilt(sos, toma.signal_ref).astype(np.float32)

    # ── Paso 2: Detección de onset (gruesa) ───────────────────────────────────

    def detectar_onsets(
        self,
        margen_db: float = 12.0,
        ruido_seg: float = 3.0,
        frame_ms: float = 20.0,
        log_cb=None,
    ):
        _log(log_cb, f"  Umbral adaptivo: piso + {margen_db} dB")
        for toma in self.tomas:
            sig  = toma.signal_ref
            sr   = toma.sr
            fn   = max(1, int(sr * frame_ms / 1000))
            nf   = len(sig) // fn

            niveles = np.array([_rms_db(sig[i*fn:(i+1)*fn]) for i in range(nf)])
            frames_ruido = min(int(ruido_seg * sr / fn), nf)
            piso_db  = float(np.median(niveles[:frames_ruido]))
            umbral   = piso_db + margen_db

            sobre = np.where(niveles > umbral)[0]
            toma.onset = int(sobre[0]) * fn if len(sobre) else 0
            _log(log_cb,
                 f"  {toma.ang:>4}°  piso={piso_db:.1f} dB  "
                 f"onset={toma.onset/sr:.3f} s")

    # ── Paso 3: Alineación por onset mediano ──────────────────────────────────

    def alinear_por_onset(self, log_cb=None):
        """
        Alinea todas las tomas usando el onset detectado individualmente.
        start_aligned_i = onset_i
        """
        _log(log_cb, "  Alineación por onset individual:")
        for toma in self.tomas:
            toma.lag           = 0
            toma.start_aligned = toma.onset
            _log(log_cb,
                 f"  {toma.ang:>4}°  onset={toma.onset/toma.sr:.3f} s")

    # ── Paso 4: Detección de offset (fin de nota) ─────────────────────────────

    def detectar_offsets(
        self,
        margen_db: float = 12.0,
        ruido_seg: float = 3.0,
        frame_ms: float = 20.0,
        log_cb=None,
    ):
        """
        Detecta el fin de nota en cada toma.

        El piso de ruido se estima en la región ANTERIOR al onset alineado
        (silencio antes de que empiece la nota), no en el comienzo de la nota.
        Si no hay suficiente señal pre-onset, se usa un piso bajo fijo (-60 dB).
        """
        _log(log_cb, "  Buscando fin de nota desde start alineado...")
        for toma in self.tomas:
            sr  = toma.sr
            fn  = max(1, int(sr * frame_ms / 1000))
            sig = toma.signal_ref

            # ── Piso de ruido: región antes del onset ──────────────────────────
            pre_onset = sig[:toma.start]   # silencio antes de la nota
            n_pre     = len(pre_onset) // fn
            if n_pre >= 3:                 # al menos 3 frames para mediana robusta
                niv_pre = np.array([_rms_db(pre_onset[i*fn:(i+1)*fn])
                                    for i in range(n_pre)])
                piso_db = float(np.median(niv_pre))
            else:
                piso_db = -60.0            # piso conservador si no hay silencio previo
            umbral = piso_db + margen_db

            # ── Búsqueda de offset en la región de nota ────────────────────────
            seg = sig[toma.start:]
            if len(seg) == 0:
                toma.offset = toma.start
                _log(log_cb, f"  {toma.ang:>4}°  [sin segmento tras start]")
                continue

            nf = len(seg) // fn
            if nf == 0:
                toma.offset = toma.start + len(seg)
                continue

            niveles = np.array([_rms_db(seg[i*fn:(i+1)*fn]) for i in range(nf)])
            sobre = np.where(niveles > umbral)[0]
            offset_frame = int(sobre[-1]) if len(sobre) else nf - 1
            toma.offset  = toma.start + (offset_frame + 1) * fn

            _log(log_cb,
                 f"  {toma.ang:>4}°  piso={piso_db:.1f} dB  "
                 f"offset={toma.offset/sr:.3f} s  "
                 f"nota={toma.note_duration/sr:.3f} s")

    # ── Paso 5: Duración común ────────────────────────────────────────────────

    def calcular_comun(self, log_cb=None):
        if not self.tomas:
            return
        sr = self.tomas[0].sr

        # ── Pre-roll común ────────────────────────────────────────────────────
        # El pre-roll de cada toma es la cantidad de muestras disponibles ANTES
        # del onset alineado (= start_aligned en el archivo original).
        # El pre-roll común es el MÍNIMO: la toma más "ajustada" al inicio del
        # archivo limita cuánto podemos retroceder sin perder información.
        # Exportar TODOS desde (start_aligned - preroll_comun) garantiza que
        # NINGUNA toma pierde contenido al inicio.
        self.preroll_comun  = min(t.start_aligned for t in self.tomas)
        self.duracion_comun = max(t.note_duration  for t in self.tomas)

        dur_total_s   = (self.preroll_comun + self.duracion_comun) / sr
        _log(log_cb, f"  Pre-roll común  : {self.preroll_comun/sr*1000:.0f} ms")
        _log(log_cb, f"  Nota más larga  : {self.duracion_comun/sr:.3f} s")
        _log(log_cb, f"  Duración export : {dur_total_s:.3f} s por toma")

        for toma in self.tomas:
            falta = self.duracion_comun - toma.note_duration
            if falta > 0:
                _log(log_cb,
                     f"  {toma.ang:>4}°  post-relleno ceros: {falta/sr:.3f} s")

    # ── Exportación ───────────────────────────────────────────────────────────

    def exportar(
        self,
        carpeta_salida: Path,
        target_sr: int | None = None,
        subtype: str = "FLOAT",
        marg_ini_ms: float = 0.0,
        marg_fin_ms: float = 0.0,
        log_cb=None,
    ):
        """
        Exporta todos los WAVs (refs + mics) alineados.

        Estructura de cada archivo exportado:
            [marg_ini_ms ms de ceros] + [nota, duracion_comun muestras] + [marg_fin_ms ms de ceros]

        El corte comienza exactamente en toma.start (onset alineado).
        Las notas más cortas que duracion_comun se rellenan con ceros al final.
        Los márgenes son silencio puro, idénticos para todas las tomas.

        Parámetros
        ----------
        target_sr   : int | None   SR de destino (None = conserva original).
        subtype     : str          "FLOAT" | "PCM_24" | "PCM_16".
        marg_ini_ms : float        Milisegundos de silencio antes del onset.
        marg_fin_ms : float        Milisegundos de silencio después del fin de nota.
        """
        carpeta_salida.mkdir(parents=True, exist_ok=True)

        total    = sum(1 + len(t.paths_mics) for t in self.tomas)
        guardado = 0

        for toma in self.tomas:
            sr     = toma.sr
            out_sr = target_sr if target_sr else sr
            ini    = toma.start          # onset exacto — sin pre-roll de audio real
            dur    = self.duracion_comun  # muestras de nota (en sr original)

            # Ceros de margen calculados en el SR de salida
            n_pre = int(marg_ini_ms / 1000 * out_sr)
            n_pos = int(marg_fin_ms  / 1000 * out_sr)

            def _cortar(sig: np.ndarray, sr_sig: int) -> np.ndarray:
                # 1. Resamplear a toma.sr para cortar con ini/dur en escala correcta
                work = sig
                if sr_sig != sr:
                    g    = gcd(sr, sr_sig)
                    work = resample_poly(sig, sr // g, sr_sig // g).astype(np.float32)
                seg = work[ini : ini + dur]
                if len(seg) < dur:                           # nota más corta → ceros al final
                    seg = np.pad(seg, (0, dur - len(seg)))
                # 2. Resamplear a out_sr si el usuario eligió otro SR
                if out_sr != sr:
                    g   = gcd(sr, out_sr)
                    seg = resample_poly(seg, out_sr // g, sr // g).astype(np.float32)
                # 3. Añadir márgenes de silencio
                return np.concatenate([
                    np.zeros(n_pre, dtype=np.float32),
                    seg.astype(np.float32),
                    np.zeros(n_pos, dtype=np.float32),
                ])

            # — Referencia — exportar SIEMPRE el original sin filtrar
            seg    = _cortar(toma.signal_ref_orig, sr)
            nombre = toma.path_ref.stem + "_alineado.wav"
            sf.write(str(carpeta_salida / nombre), seg, out_sr, subtype=subtype)
            guardado += 1
            _log(log_cb, f"  [{guardado}/{total}] {nombre}")

            # — Micrófonos —
            for mic_num, mic_path in sorted(toma.paths_mics.items()):
                try:
                    sig_m, sr_m = sf.read(str(mic_path), dtype="float32")
                    if sig_m.ndim > 1:
                        sig_m = sig_m[:, 0]
                    seg_m    = _cortar(sig_m, int(sr_m))
                    nombre_m = mic_path.stem + "_alineado.wav"
                    sf.write(str(carpeta_salida / nombre_m), seg_m, out_sr,
                             subtype=subtype)
                    guardado += 1
                    if guardado % 40 == 0:
                        _log(log_cb, f"  [{guardado}/{total}] ...")
                except Exception as e:
                    _log(log_cb, f"  [WARN] {mic_path.name}: {e}")

        dur_total_s = (n_pre + int(dur * out_sr / sr) + n_pos) / out_sr
        _log(log_cb,
             f"  Exportación completa: {guardado} archivos · "
             f"{dur_total_s:.3f} s por toma · {out_sr} Hz  [{subtype}]  "
             f"→ {carpeta_salida}")


# ══════════════════════════════════════════════════════════════════════════════
# Worker Qt (corre MotorAlineacion en un hilo)
# ══════════════════════════════════════════════════════════════════════════════

class ProcesadorWorker(QObject):
    progreso  = pyqtSignal(int)
    log       = pyqtSignal(str)
    terminado = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, motor: MotorAlineacion, pasos: dict):
        super().__init__()
        self._motor = motor
        self._pasos = pasos

    def run(self):
        try:
            m   = self._motor
            p   = self._pasos
            log = lambda msg: self.log.emit(msg)

            if p.get("filtrar"):
                self.log.emit("── Filtro pasa altos ──────────────────")
                m.filtrar(p["fc_hz"], log_cb=log)
                self.progreso.emit(20)

            self.log.emit("── Detección de onsets ─────────────────")
            m.detectar_onsets(p["margen_db"], log_cb=log)
            self.progreso.emit(45)

            self.log.emit("── Alineación por onset ────────────────")
            m.alinear_por_onset(log_cb=log)
            self.progreso.emit(65)

            self.log.emit("── Detección de offsets ────────────────")
            m.detectar_offsets(p["margen_db"], log_cb=log)
            self.progreso.emit(80)

            self.log.emit("── Duración común ──────────────────────")
            m.calcular_comun(log_cb=log)
            self.progreso.emit(100)

            self.terminado.emit()
        except Exception as e:
            self.error.emit(str(e))


class ExportWorker(QObject):
    log       = pyqtSignal(str)
    terminado = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(
        self,
        motor: MotorAlineacion,
        carpeta: Path,
        target_sr: int | None = None,
        subtype: str = "FLOAT",
        marg_ini_ms: float = 0.0,
        marg_fin_ms: float = 0.0,
    ):
        super().__init__()
        self._motor       = motor
        self._carpeta     = carpeta
        self._target_sr   = target_sr
        self._subtype     = subtype
        self._marg_ini_ms = marg_ini_ms
        self._marg_fin_ms = marg_fin_ms

    def run(self):
        try:
            self._motor.exportar(
                self._carpeta,
                target_sr   = self._target_sr,
                subtype     = self._subtype,
                marg_ini_ms = self._marg_ini_ms,
                marg_fin_ms = self._marg_fin_ms,
                log_cb      = lambda m: self.log.emit(m),
            )
            self.terminado.emit()
        except Exception as e:
            self.error.emit(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Diálogo de opciones de exportación
# ══════════════════════════════════════════════════════════════════════════════

class ExportDialog(QDialog):
    """
    Popup que aparece al pulsar 'Exportar WAVs'.
    Permite elegir sample rate de destino y profundidad de bits.
    """

    # Sample rates comunes, en orden descendente
    _ALL_RATES = [192000, 96000, 88200, 48000, 44100, 32000, 22050, 16000, 8000]

    def __init__(self, source_sr: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opciones de exportación")
        self.setModal(True)
        self.setFixedWidth(360)

        # Solo ofrecer rates ≤ source_sr
        valid_rates = [r for r in self._ALL_RATES if r <= source_sr]

        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(18, 16, 18, 16)

        # ── Título ────────────────────────────────────────────────────────────
        titulo = QLabel("⚙  Configuración de exportación")
        titulo.setStyleSheet("font-size:13px; font-weight:bold; color:#5cc8d8;")
        lay.addWidget(titulo)

        # ── Formulario ────────────────────────────────────────────────────────
        form = QGridLayout(); form.setSpacing(10)

        # Sample rate
        form.addWidget(QLabel("Sample rate:"), 0, 0)
        self._combo_sr = QComboBox()
        for r in valid_rates:
            label = f"{r:,} Hz".replace(",", ".")
            if r == source_sr:
                label += "  (original)"
            self._combo_sr.addItem(label, r)
        # Seleccionar el rate original por defecto
        orig_idx = next(
            (i for i, r in enumerate(valid_rates) if r == source_sr), 0)
        self._combo_sr.setCurrentIndex(orig_idx)
        form.addWidget(self._combo_sr, 0, 1)

        # Profundidad de bits
        form.addWidget(QLabel("Profundidad de bits:"), 1, 0)
        self._combo_bits = QComboBox()
        self._combo_bits.addItem("32-bit Float  (sin pérdidas)",  "FLOAT")
        self._combo_bits.addItem("24-bit PCM",                    "PCM_24")
        self._combo_bits.addItem("16-bit PCM",                    "PCM_16")
        form.addWidget(self._combo_bits, 1, 1)

        lay.addLayout(form)

        # ── Nota informativa ──────────────────────────────────────────────────
        info = QLabel(
            "ℹ  El re-muestreo aplica a todos los WAVs exportados\n"
            "(referencias y micrófonos). Se usa resample_poly de SciPy."
        )
        info.setStyleSheet("font-size:10px; color:#6699aa;")
        info.setWordWrap(True)
        lay.addWidget(info)

        # ── Botones OK / Cancelar ─────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("✔  Exportar")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ── Resultado ─────────────────────────────────────────────────────────────

    @property
    def target_sr(self) -> int:
        return self._combo_sr.currentData()

    @property
    def subtype(self) -> str:
        return self._combo_bits.currentData()


# ══════════════════════════════════════════════════════════════════════════════
# Visor de formas de onda  (pyqtgraph — nativo Qt, sin artefactos de foco)
# ══════════════════════════════════════════════════════════════════════════════

class VisorOndasWidget(QWidget):
    """
    Muestra las formas de onda de las referencias, apiladas verticalmente.
    Visualización tipo DAW: envolvente min/max por bloque.
    Permite ver el estado 'original' (sin alinear) o 'alineado'.
    """

    # Paleta tab20 como cadenas hex
    COLORES = [
        "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c",
        "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5",
        "#8c564b", "#c49c94", "#e377c2", "#f7b6d2", "#7f7f7f",
        "#c7c7c7", "#bcbd22", "#dbdb8d", "#17becf", "#9edae5",
    ]
    _N_BLOQUES = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)

        self._pw = pg.PlotWidget()
        self._pw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pi = self._pw.getPlotItem()
        pi.getAxis("left").hide()
        pi.getAxis("bottom").setPen(pg.mkPen("#444466"))
        pi.getAxis("bottom").setTextPen(pg.mkPen("#888888"))
        pi.getAxis("bottom").setLabel("Tiempo (s)", color="#aaaaaa")
        pi.showGrid(x=True, y=False, alpha=0.12)
        lay.addWidget(self._pw)

        self._motor: MotorAlineacion | None = None
        self._modo   = "original"
        self._cursor: pg.InfiniteLine | None = None

    def set_motor(self, motor: MotorAlineacion):
        self._motor = motor

    def mostrar(self, modo: str = "alineado",
                marg_ini_ms: float = 0.0,
                marg_fin_ms: float = 0.0):
        self._modo = modo
        pi = self._pw.getPlotItem()
        pi.clear()
        self._cursor = None

        if not self._motor or not self._motor.tomas:
            return

        m  = self._motor
        sr = m.tomas[0].sr

        for i, toma in enumerate(m.tomas):
            sig = toma.signal_ref_orig if toma.signal_ref_orig is not None \
                  else toma.signal_ref
            col = self.COLORES[i % len(self.COLORES)]
            sep = float(i * 2.2)

            if modo == "original":
                fragmento   = sig
                t_offset    = 0.0          # eje de tiempo: segundos absolutos
            else:
                start  = toma.start
                dur_c  = m.duracion_comun
                marg_i = int(marg_ini_ms / 1000 * sr)
                marg_f = int(marg_fin_ms  / 1000 * sr)
                total  = marg_i + dur_c + marg_f

                # Inicio real en el archivo (podría no haber suficiente pre-roll)
                ini_real     = max(0, start - marg_i)
                zeros_before = max(0, marg_i - start)   # ceros al inicio si falta

                fragmento = sig[ini_real : ini_real + total - zeros_before]
                if zeros_before:
                    fragmento = np.concatenate(
                        [np.zeros(zeros_before, dtype=np.float32), fragmento])
                if len(fragmento) < total:
                    fragmento = np.pad(fragmento, (0, total - len(fragmento)))

                # t=0 = onset: el pre-roll aparece con tiempo negativo
                t_offset = -marg_ini_ms / 1000.0

            pico = np.max(np.abs(fragmento)) + 1e-9
            frag_norm = fragmento / pico
            t_env, mins, maxs = _envolvente(frag_norm, self._N_BLOQUES, sr)
            t_env = t_env + t_offset   # shift: t=0 = onset en modo alineado

            # Envolvente rellena (estilo DAW)
            qc = QColor(col)
            qc.setAlpha(191)                    # 75 % opacidad
            pen_inv = pg.mkPen(None)            # curvas invisibles
            c1   = pg.PlotDataItem(t_env, mins + sep, pen=pen_inv)
            c2   = pg.PlotDataItem(t_env, maxs + sep, pen=pen_inv)
            fill = pg.FillBetweenItem(c1, c2, brush=pg.mkBrush(qc))
            pi.addItem(c1); pi.addItem(c2); pi.addItem(fill)

            # Línea base tenue
            qc_base = QColor(col); qc_base.setAlpha(77)
            pi.addItem(pg.InfiniteLine(
                pos=sep, angle=0, pen=pg.mkPen(qc_base, width=0.5)))

            # Marcadores verticales
            # En modo original: tiempo absoluto; en alineado: t=0 es el onset
            if modo == "original" and toma.onset > 0:
                pi.addItem(pg.InfiniteLine(
                    pos=toma.onset / sr, angle=90,
                    pen=pg.mkPen(col, width=1.0,
                                 style=Qt.PenStyle.DashLine)))
            elif modo == "alineado":
                nota_t = toma.note_duration / sr   # ya en escala t=0=onset
                dur_t  = m.duracion_comun / sr
                if nota_t < dur_t - 0.05:
                    pi.addItem(pg.InfiniteLine(
                        pos=nota_t, angle=90,
                        pen=pg.mkPen(col, width=0.8,
                                     style=Qt.PenStyle.DotLine)))

            # Etiqueta de ángulo — al inicio del fragmento visible
            lbl = pg.TextItem(f"{toma.ang}°", color=col, anchor=(0.0, 0.5))
            lbl.setPos(float(t_env[0]), sep)
            pi.addItem(lbl)

        # Línea blanca = duración común (modo alineado, en escala t=0=onset)
        if modo == "alineado" and m.duracion_comun > 0:
            dur_s = m.duracion_comun / sr
            qc_w = QColor("white"); qc_w.setAlpha(89)
            pi.addItem(pg.InfiniteLine(
                pos=dur_s, angle=90,
                pen=pg.mkPen(qc_w, width=1.5)))

        # Línea vertical en t=0 (onset) en modo alineado
        if modo == "alineado":
            qc_onset = QColor("#ffff66"); qc_onset.setAlpha(120)
            pi.addItem(pg.InfiniteLine(
                pos=0.0, angle=90,
                pen=pg.mkPen(qc_onset, width=1.0,
                             style=Qt.PenStyle.DashLine)))

        titulo = ("Original  [-- = onset detectado]"
                  if modo == "original"
                  else "Alineado  [··· = fin nota · — = duración común]")
        pi.setTitle(titulo, color="#cccccc", size="8pt")

    def set_cursor(self, t: float):
        pi = self._pw.getPlotItem()
        if self._cursor is not None:
            pi.removeItem(self._cursor)
        self._cursor = pg.InfiniteLine(
            pos=t, angle=90, pen=pg.mkPen("#ff8c00", width=1.5))
        pi.addItem(self._cursor)


# ══════════════════════════════════════════════════════════════════════════════
# Ventana principal
# ══════════════════════════════════════════════════════════════════════════════

class AlineadorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alineador Temporal — Directividad Vocal")
        self.resize(1440, 860)
        self._motor   = MotorAlineacion()
        self._thread: QThread | None = None
        self._playback_sig: np.ndarray | None = None
        self._playback_sr:  int = 44100

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Barra superior: carga + acciones principales
        root.addWidget(self._barra_superior())

        # Área principal: sidebar izquierdo + visor grande
        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(self._panel_sidebar())
        main.addWidget(self._panel_visor())
        main.setStretchFactor(0, 0)
        main.setStretchFactor(1, 1)
        main.setSizes([210, 1200])
        root.addWidget(main, stretch=1)

        # Panel inferior: log + tabla en tabs
        root.addWidget(self._panel_inferior())

    # ── Construcción UI ───────────────────────────────────────────────────────

    def _barra_superior(self) -> QWidget:
        """Toolbar superior: carga de archivos, acción principal y exportación."""
        bar = QWidget()
        bar.setObjectName("barraSuperior")
        lay = QVBoxLayout(bar)
        lay.setSpacing(5)
        lay.setContentsMargins(10, 8, 10, 6)

        # ── Fila 1: carpeta · plantilla · dinámica · cargar ──────────────────
        f1 = QHBoxLayout(); f1.setSpacing(6)

        f1.addWidget(QLabel("📁 Carpeta:"))
        self._campo_carpeta = QLineEdit()
        self._campo_carpeta.setPlaceholderText("Carpeta con los WAVs de medición…")
        f1.addWidget(self._campo_carpeta, stretch=3)

        btn_dir = QPushButton("…")
        btn_dir.setFixedWidth(32)
        btn_dir.setObjectName("btnBrowse")
        btn_dir.setToolTip("Explorar carpeta de mediciones")
        btn_dir.clicked.connect(self._explorar_carpeta)
        f1.addWidget(btn_dir)

        f1.addSpacing(10)
        f1.addWidget(QLabel("Plantilla:"))
        self._campo_tmpl_refs = QLineEdit("mic_ref_ang_{DIN}_{ANG}.wav")
        self._campo_tmpl_refs.setMinimumWidth(190)
        self._campo_tmpl_refs.setToolTip("Tokens: {DIN} = dinámica  {ANG} = ángulo")
        f1.addWidget(self._campo_tmpl_refs, stretch=2)

        f1.addSpacing(10)
        f1.addWidget(QLabel("Dinámica:"))
        # Editable: se auto-completa al cargar la carpeta
        self._combo_din = QComboBox()
        self._combo_din.setEditable(True)
        self._combo_din.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo_din.lineEdit().setPlaceholderText("ej: forte, piano…")
        self._combo_din.setMinimumWidth(110)
        self._combo_din.setToolTip(
            "Se detecta automáticamente al abrir la carpeta.\n"
            "También podés escribir el nombre de la dinámica.")
        f1.addWidget(self._combo_din)

        btn_cargar = QPushButton("⬇  Cargar")
        btn_cargar.setObjectName("btnCargar")
        btn_cargar.setMinimumWidth(96)
        btn_cargar.setMinimumHeight(32)
        btn_cargar.clicked.connect(self._on_cargar)
        f1.addWidget(btn_cargar)

        lay.addLayout(f1)

        # ── Fila 2: analizar · progreso · exportar ────────────────────────────
        f2 = QHBoxLayout(); f2.setSpacing(8)

        self._btn_analizar = QPushButton("▶  Detectar y alinear")
        self._btn_analizar.setObjectName("btnAnalizar")
        self._btn_analizar.setMinimumWidth(165)
        self._btn_analizar.setMinimumHeight(34)
        self._btn_analizar.setEnabled(False)
        self._btn_analizar.clicked.connect(self._on_analizar)
        f2.addWidget(self._btn_analizar)

        f2.addSpacing(10)

        self._barra = QProgressBar()
        self._barra.setRange(0, 100)
        self._barra.setTextVisible(True)
        self._barra.setMinimumWidth(160)
        self._barra.setMaximumWidth(280)
        self._barra.setFixedHeight(20)
        f2.addWidget(self._barra)

        f2.addStretch()

        f2.addWidget(QLabel("Exportar a:"))
        self._campo_export = QLineEdit()
        self._campo_export.setPlaceholderText("Carpeta de destino…")
        f2.addWidget(self._campo_export, stretch=2)
        btn_exp_dir = QPushButton("…")
        btn_exp_dir.setObjectName("btnBrowse")
        btn_exp_dir.setFixedWidth(32)
        btn_exp_dir.clicked.connect(self._explorar_export)
        f2.addWidget(btn_exp_dir)

        self._btn_exportar = QPushButton("💾  Exportar WAVs")
        self._btn_exportar.setObjectName("btnExportar")
        self._btn_exportar.setMinimumWidth(140)
        self._btn_exportar.setMinimumHeight(34)
        self._btn_exportar.setEnabled(False)
        self._btn_exportar.clicked.connect(self._on_exportar)
        f2.addWidget(self._btn_exportar)

        lay.addLayout(f2)
        return bar

    def _panel_sidebar(self) -> QWidget:
        """Panel lateral izquierdo: parámetros de análisis, vistas y reproducción."""
        w = QWidget()
        w.setFixedWidth(212)
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.setContentsMargins(6, 8, 6, 6)

        # ── Filtro pasa-altos ─────────────────────────────────────────────────
        gb_hp = QGroupBox("Filtro pasa-altos")
        gl_hp = QGridLayout(gb_hp); gl_hp.setSpacing(6)

        self._chk_filtrar = QCheckBox("Aplicar HP Butterworth 4°")
        self._chk_filtrar.setChecked(True)

        self._spin_fc = QDoubleSpinBox()
        self._spin_fc.setRange(20, 500); self._spin_fc.setValue(100)
        self._spin_fc.setSuffix(" Hz")

        lbl_fc = QLabel("Fc:")
        gl_hp.addWidget(self._chk_filtrar, 0, 0, 1, 2)
        gl_hp.addWidget(lbl_fc,            1, 0)
        gl_hp.addWidget(self._spin_fc,     1, 1)
        lay.addWidget(gb_hp)

        # ── Detección de onset ────────────────────────────────────────────────
        gb_onset = QGroupBox("Detección de onset")
        gl_on = QGridLayout(gb_onset); gl_on.setSpacing(6)

        self._spin_margen = QDoubleSpinBox()
        self._spin_margen.setRange(3, 40); self._spin_margen.setValue(12)
        self._spin_margen.setSuffix(" dB")

        lbl_margen = QLabel("Umbral:")
        gl_on.addWidget(lbl_margen,        0, 0)
        gl_on.addWidget(self._spin_margen, 0, 1)
        lay.addWidget(gb_onset)

        # ── Vista de ondas ────────────────────────────────────────────────────
        gb_vista = QGroupBox("👁  Vista")
        vl_v = QVBoxLayout(gb_vista); vl_v.setSpacing(5)

        hl_v = QHBoxLayout(); hl_v.setSpacing(4)
        self._btn_orig = QPushButton("Original")
        self._btn_alin = QPushButton("Alineado")
        self._btn_orig.setObjectName("btnVista")
        self._btn_alin.setObjectName("btnVista")
        for b in (self._btn_orig, self._btn_alin):
            b.setEnabled(False)
        self._btn_orig.clicked.connect(
            lambda: (self._visor.mostrar("original"), self._set_vista_activa("original")))
        self._btn_alin.clicked.connect(
            lambda: (self._mostrar_alineado(), self._set_vista_activa("alineado")))
        hl_v.addWidget(self._btn_orig)
        hl_v.addWidget(self._btn_alin)
        vl_v.addLayout(hl_v)

        lbl_ctx = QLabel("Contexto en vista alineada:")
        lbl_ctx.setStyleSheet("color: #6a9ab0; margin-top: 4px;")
        vl_v.addWidget(lbl_ctx)

        gl_m = QGridLayout(); gl_m.setSpacing(4)
        self._spin_marg_ini = QDoubleSpinBox()
        self._spin_marg_ini.setRange(0, 2000); self._spin_marg_ini.setValue(50)
        self._spin_marg_ini.setSuffix(" ms")
        self._spin_marg_ini.setToolTip("Pre-roll antes del onset — muestra el ataque")
        self._spin_marg_ini.valueChanged.connect(self._refrescar_si_alineado)

        self._spin_marg_fin = QDoubleSpinBox()
        self._spin_marg_fin.setRange(0, 5000); self._spin_marg_fin.setValue(300)
        self._spin_marg_fin.setSuffix(" ms")
        self._spin_marg_fin.setToolTip("Cola después del fin de nota")
        self._spin_marg_fin.valueChanged.connect(self._refrescar_si_alineado)

        gl_m.addWidget(QLabel("Inicio:"),       0, 0)
        gl_m.addWidget(self._spin_marg_ini,     0, 1)
        gl_m.addWidget(QLabel("Final:"),         1, 0)
        gl_m.addWidget(self._spin_marg_fin,      1, 1)
        vl_v.addLayout(gl_m)
        lay.addWidget(gb_vista)

        # ── Reproducción ──────────────────────────────────────────────────────
        gb_play = QGroupBox("▶  Reproducción")
        vl_p = QVBoxLayout(gb_play); vl_p.setSpacing(5)

        hl_sel = QHBoxLayout()
        hl_sel.addWidget(QLabel("Toma:"))
        self._combo_canal = QComboBox()
        self._combo_canal.setToolTip("Toma a reproducir")
        hl_sel.addWidget(self._combo_canal, stretch=1)
        vl_p.addLayout(hl_sel)

        hl_pb = QHBoxLayout(); hl_pb.setSpacing(4)
        self._btn_play = QPushButton("▶  Play")
        self._btn_stop = QPushButton("■  Stop")
        self._btn_play.setObjectName("btnPlay")
        self._btn_stop.setObjectName("btnStop")
        self._btn_play.clicked.connect(self._on_play)
        self._btn_stop.clicked.connect(self._on_stop)
        if not _SD_OK:
            self._btn_play.setEnabled(False)
            self._btn_play.setToolTip("pip install sounddevice")
        hl_pb.addWidget(self._btn_play)
        hl_pb.addWidget(self._btn_stop)
        vl_p.addLayout(hl_pb)

        self._chk_alineado_play = QCheckBox("Segmento alineado")
        self._chk_alineado_play.setChecked(True)
        vl_p.addWidget(self._chk_alineado_play)

        lay.addWidget(gb_play)
        lay.addStretch()
        return w

    def _panel_visor(self) -> QWidget:
        """Visor central de formas de onda (pyqtgraph)."""
        self._visor = VisorOndasWidget()
        return self._visor

    def _panel_inferior(self) -> QWidget:
        """Panel inferior con tabs: Log de proceso y tabla de Resultados."""
        w = QWidget()
        w.setFixedHeight(195)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(0)

        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        # Tab: Log ─────────────────────────────────────────────────────────────
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 8))
        tabs.addTab(self._log, "📋 Log")

        # Tab: Resultados ──────────────────────────────────────────────────────
        self._tabla = QTableWidget()
        self._tabla.setColumnCount(6)
        self._tabla.setHorizontalHeaderLabels(
            ["Ángulo", "Onset (s)", "Offset (s)", "Nota (s)",
             "Start export (s)", "Estado"])
        self._tabla.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tabla.setAlternatingRowColors(True)
        tabs.addTab(self._tabla, "📊 Resultados")

        lay.addWidget(tabs)
        return w

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _detectar_dinamicas(self, carpeta: Path):
        """
        Escanea los WAVs de la carpeta y extrae los valores únicos de {DIN}
        según la plantilla de referencia actual. Rellena el combo de dinámica.
        """
        try:
            re_refs = _compilar_template(self._campo_tmpl_refs.text())
        except Exception:
            return

        dins: set[str] = set()
        for wav in carpeta.glob("*.wav"):
            m = re_refs.match(wav.name)
            if m:
                try:
                    dins.add(m.group("din"))
                except IndexError:
                    pass

        if not dins:
            return

        actual = self._combo_din.currentText()
        self._combo_din.blockSignals(True)
        self._combo_din.clear()
        for d in sorted(dins):
            self._combo_din.addItem(d)
        # Mantener la selección previa si sigue siendo válida
        if actual in dins:
            self._combo_din.setCurrentText(actual)
        else:
            self._combo_din.setCurrentIndex(0)
        self._combo_din.blockSignals(False)

    def _explorar_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de mediciones")
        if ruta:
            self._campo_carpeta.setText(ruta)
            # Sugerir carpeta de exportación
            self._campo_export.setText(str(Path(ruta) / "_alineado"))
            # Auto-detectar dinámica desde los nombres de archivo
            self._detectar_dinamicas(Path(ruta))

    def _explorar_export(self):
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de exportación")
        if ruta:
            self._campo_export.setText(ruta)

    def _on_cargar(self):
        carpeta = Path(self._campo_carpeta.text().strip())
        if not carpeta.exists():
            self._agregar_log("[ERROR] La carpeta no existe.")
            return
        self._agregar_log(f"── Cargando '{self._combo_din.currentText()}' ──")
        try:
            self._motor.cargar(
                carpeta,
                self._combo_din.currentText(),
                template_mics = "mic_{MIC}_ang_{DIN}_{ANG}.wav",  # default fijo
                template_refs = self._campo_tmpl_refs.text(),
                log_cb=self._agregar_log,
            )
            n = len(self._motor.tomas)
            self._agregar_log(f"[OK] {n} tomas cargadas.")
            self._btn_analizar.setEnabled(True)
            self._visor.set_motor(self._motor)
            self._visor.mostrar("original")   # rápido: señales decimadas a 3000 pts
            self._btn_orig.setEnabled(True)
            self._actualizar_combo_canal()
            self._agregar_log("[OK] Presioná 'Detectar y alinear' para continuar.")
        except Exception as e:
            self._agregar_log(f"[ERROR] {e}")

    def _on_analizar(self):
        if self._thread and self._thread.isRunning():
            return

        pasos = {
            "filtrar":   self._chk_filtrar.isChecked(),
            "fc_hz":     self._spin_fc.value(),
            "margen_db": self._spin_margen.value(),
        }

        self._btn_analizar.setEnabled(False)
        self._btn_exportar.setEnabled(False)
        self._barra.setValue(0)
        self._agregar_log("── Iniciando análisis ──────────────────")

        self._worker = ProcesadorWorker(self._motor, pasos)   # mantener ref → no GC
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progreso.connect(self._barra.setValue)
        self._worker.log.connect(self._agregar_log)
        self._worker.terminado.connect(self._on_analisis_terminado)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _mostrar_alineado(self):
        """Muestra la vista alineada con los márgenes actuales."""
        self._visor.mostrar(
            "alineado",
            self._spin_marg_ini.value(),
            self._spin_marg_fin.value(),
        )

    def _set_vista_activa(self, modo: str):
        """Resalta visualmente el botón de la vista activa."""
        _activo = (
            "QPushButton{background:#1a3a50;border:2px solid #00aacc;"
            "color:#44ddff;border-radius:5px;font-weight:bold;}"
        )
        _inactivo = ""   # vuelve al estilo global
        if modo == "original":
            self._btn_orig.setStyleSheet(_activo)
            self._btn_alin.setStyleSheet(_inactivo)
        else:
            self._btn_orig.setStyleSheet(_inactivo)
            self._btn_alin.setStyleSheet(_activo)

    def _refrescar_si_alineado(self):
        """Se llama cuando cambian los spinboxes de margen — refresca en vivo."""
        if self._visor._modo == "alineado":
            self._mostrar_alineado()

    def _on_analisis_terminado(self):
        if self._thread:
            self._thread.quit()
        self._btn_analizar.setEnabled(True)
        self._btn_exportar.setEnabled(True)
        self._btn_alin.setEnabled(True)
        self._agregar_log("[OK] Análisis completado. Graficando...")
        self._actualizar_tabla()
        # Ajustar spinbox de inicio al pre-roll calculado (mínimo garantizado)
        if self._motor.tomas:
            sr = self._motor.tomas[0].sr
            preroll_ms = self._motor.preroll_comun / sr * 1000
            self._spin_marg_ini.blockSignals(True)
            self._spin_marg_ini.setValue(max(preroll_ms, self._spin_marg_ini.value()))
            self._spin_marg_ini.blockSignals(False)
        self._mostrar_alineado()
        self._agregar_log("[OK] Listo. Usá 'Original' / 'Alineado' para comparar.")

    def _on_exportar(self):
        carpeta_exp = Path(self._campo_export.text().strip())
        if not carpeta_exp:
            self._agregar_log("[ERROR] Especificá la carpeta de exportación.")
            return
        if self._motor.duracion_comun == 0:
            self._agregar_log("[ERROR] Primero ejecutá el análisis.")
            return

        # Mostrar diálogo de opciones de exportación
        source_sr = self._motor.tomas[0].sr if self._motor.tomas else 44100
        dlg = ExportDialog(source_sr, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return   # usuario canceló

        target_sr = dlg.target_sr
        subtype   = dlg.subtype
        marg_ini  = self._spin_marg_ini.value()
        marg_fin  = self._spin_marg_fin.value()

        self._agregar_log(
            f"── Exportando a {carpeta_exp} ──\n"
            f"   SR: {target_sr} Hz  |  {subtype}\n"
            f"   Pre-silencio: {marg_ini:.0f} ms  |  Post-silencio: {marg_fin:.0f} ms"
        )
        self._btn_exportar.setEnabled(False)

        self._worker = ExportWorker(        # mantener ref → no GC
            self._motor, carpeta_exp, target_sr, subtype, marg_ini, marg_fin)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._agregar_log)
        self._worker.terminado.connect(self._on_export_terminado)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_export_terminado(self):
        if self._thread:
            self._thread.quit()
        self._btn_exportar.setEnabled(True)
        self._agregar_log("[OK] Exportación completa.")

    def _on_error(self, msg: str):
        if self._thread:
            self._thread.quit()
        self._agregar_log(f"[ERROR] {msg}")
        self._btn_analizar.setEnabled(True)

    def _on_play(self):
        if not _SD_OK:
            return
        idx = self._combo_canal.currentIndex()
        if idx < 0 or idx >= len(self._motor.tomas):
            return
        toma = self._motor.tomas[idx]
        sig  = toma.signal_ref
        sr   = toma.sr

        if self._chk_alineado_play.isChecked() and self._motor.duracion_comun > 0:
            ini = toma.start
            dur = self._motor.duracion_comun
            seg = sig[ini : ini + dur]
            if len(seg) < dur:
                seg = np.pad(seg, (0, dur - len(seg)))
        else:
            seg = sig

        sd.play(seg.astype(np.float32), sr)

    def _on_stop(self):
        if _SD_OK:
            sd.stop()

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _actualizar_tabla(self):
        m = self._motor
        self._tabla.setRowCount(len(m.tomas))
        sr = m.tomas[0].sr if m.tomas else 44100

        for i, toma in enumerate(m.tomas):
            relleno = m.duracion_comun - toma.note_duration
            estado  = "OK" if relleno <= 0 else f"+{relleno/sr:.2f} s ceros"
            color   = QColor("#2a5c2a") if relleno <= 0 else QColor("#5c3a1a")

            valores = [
                f"{toma.ang}°",
                f"{toma.onset/sr:.3f}",
                f"{toma.offset/sr:.3f}",
                f"{toma.note_duration/sr:.3f}",
                f"{toma.start/sr:.3f}",
                estado,
            ]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(color)
                self._tabla.setItem(i, j, item)

    def _actualizar_combo_canal(self):
        self._combo_canal.clear()
        for toma in self._motor.tomas:
            self._combo_canal.addItem(f"{toma.ang}°")

    def _agregar_log(self, msg: str):
        self._log.append(msg)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )


# ══════════════════════════════════════════════════════════════════════════════
# Funciones auxiliares (sin estado)
# ══════════════════════════════════════════════════════════════════════════════

def _envolvente(sig: np.ndarray, n_bloques: int, sr: int):
    """
    Calcula la envolvente min/max por bloques para visualización tipo DAW.

    A diferencia de sig[::paso], garantiza que ningún pico queda oculto:
    cada bloque aporta su valor máximo Y mínimo, así fill_between muestra
    la forma real de la onda sin importar cuántas muestras haya por píxel.

    Returns
    -------
    t    : np.ndarray  eje de tiempo (centro de cada bloque, en segundos)
    mins : np.ndarray  mínimo de cada bloque
    maxs : np.ndarray  máximo de cada bloque
    """
    n      = len(sig)
    bloque = max(1, n // n_bloques)
    n_real = n // bloque          # bloques completos
    datos  = sig[:n_real * bloque].reshape(n_real, bloque)
    mins   = datos.min(axis=1)
    maxs   = datos.max(axis=1)
    t      = (np.arange(n_real) * bloque + bloque / 2) / sr
    return t, mins, maxs


def _gcc_phat(sig: np.ndarray, ref: np.ndarray, max_lag: int) -> int:
    """
    GCC-PHAT: retorna el delay de `sig` respecto a `ref` en muestras.
    delay > 0 → sig está retrasada (su contenido llega DESPUÉS que ref).
    """
    n     = len(sig)
    n_fft = int(2 ** np.ceil(np.log2(2 * n - 1)))

    A   = np.fft.rfft(sig, n=n_fft)
    R   = np.fft.rfft(ref, n=n_fft)
    X   = A * np.conj(R)
    den = np.abs(X)
    den[den < 1e-10] = 1e-10
    X  /= den

    cc  = np.fft.irfft(X, n=n_fft)

    pos = cc[:max_lag + 1]
    neg = cc[n_fft - max_lag:]
    pi  = int(np.argmax(pos))
    ni  = int(np.argmax(neg))

    return pi if pos[pi] >= neg[ni] else -(max_lag - ni)


def _rms_db(frame: np.ndarray) -> float:
    rms = np.sqrt(np.mean(frame ** 2))
    return float(20 * np.log10(rms + 1e-10))


def _log(cb, msg: str):
    if cb:
        cb(msg)


def _compilar_template(template: str) -> re.Pattern:
    MARCADORES = {
        "{MIC}": r"(?P<mic>\d+)",
        "{DIN}": r"(?P<din>[^_]+)",
        "{ANG}": r"(?P<ang>\d+)",
    }
    marcadores = sorted(MARCADORES.keys(), key=len, reverse=True)
    partes, resto = [], template
    while resto:
        encontrado = False
        for m in marcadores:
            if resto.startswith(m):
                partes.append(MARCADORES[m])
                resto = resto[len(m):]
                encontrado = True
                break
        if not encontrado:
            partes.append(re.escape(resto[0]))
            resto = resto[1:]
    return re.compile("".join(partes) + "$", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════════════════
# Punto de entrada
# ══════════════════════════════════════════════════════════════════════════════

def _make_checkmark_svg() -> str:
    """
    Genera un SVG de tilde blanco en un archivo temporal.
    Qt no soporta data-URIs en QSS, así que necesitamos un archivo real.
    El archivo se elimina automáticamente al salir del programa.
    """
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14">'
        '<polyline points="2,8 5.5,12.5 12,2" '
        'stroke="white" stroke-width="2.4" '
        'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )
    tmp = tempfile.NamedTemporaryFile(
        suffix=".svg", delete=False, mode="w", encoding="utf-8")
    tmp.write(svg)
    tmp.close()
    p = Path(tmp.name)
    atexit.register(lambda: p.unlink(missing_ok=True))
    return tmp.name.replace("\\", "/")


_CHECKMARK_URL = _make_checkmark_svg()

# Estilos del indicador de checkbox — se aplican SIEMPRE (con o sin qt-material)
_CHECKBOX_EXTRA = """
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1.5px solid #445a7a;
    border-radius: 4px;
    background-color: #0e1422;
}
QCheckBox::indicator:unchecked:hover { border-color: #44aacc; }
QCheckBox::indicator:checked {
    background-color: #009db5;
    border-color: #00ccee;
    image: url(%%CHECK%%);
}
""".replace("%%CHECK%%", _CHECKMARK_URL)


_STYLE = """
/* ── Base ─────────────────────────────────────────────────────────────────── */
QWidget {
    background-color: #161b28;
    color: #ccd6ed;
    font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
    font-size: 12px;
}
QMainWindow, QDialog { background-color: #161b28; }

/* ── Group boxes ─────────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #2a3a5a;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    color: #4ec9e0;
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.3px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}

/* ── Botones por defecto ─────────────────────────────────────────────────── */
QPushButton {
    background-color: #1e2840;
    border: 1px solid #3a4a6a;
    border-radius: 6px;
    padding: 6px 14px;
    color: #a8c0e0;
    font-size: 12px;
}
QPushButton:hover  { background-color: #26355a; border-color: #557aaa; color: #c8deff; }
QPushButton:pressed{ background-color: #141e32; }
QPushButton:disabled { color: #35435a; border-color: #1e2a3a; background: #141824; }

/* ── Botón principal: Detectar y alinear (verde lima) ─────────────────────── */
QPushButton#btnAnalizar {
    background-color: #0d3820;
    border: 1.5px solid #28a855;
    color: #44ee88;
    font-weight: bold;
    font-size: 13px;
}
QPushButton#btnAnalizar:hover  { background-color: #124a2a; border-color: #44cc66; }
QPushButton#btnAnalizar:pressed{ background-color: #0a2818; }
QPushButton#btnAnalizar:disabled {
    background: #0a1810; color: #235030; border-color: #142515;
}

/* ── Botón de exportar (ámbar) ──────────────────────────────────────────── */
QPushButton#btnExportar {
    background-color: #3a2600;
    border: 1.5px solid #cc8800;
    color: #ffcc44;
    font-weight: bold;
    font-size: 13px;
}
QPushButton#btnExportar:hover  { background-color: #4a3200; border-color: #ffaa00; }
QPushButton#btnExportar:pressed{ background-color: #281a00; }
QPushButton#btnExportar:disabled {
    background: #1a1500; color: #554400; border-color: #2a2000;
}

/* ── Botón Cargar (cian suave) ────────────────────────────────────────────── */
QPushButton#btnCargar {
    background-color: #0d2e3a;
    border: 1.5px solid #008faa;
    color: #44ccee;
    font-weight: bold;
}
QPushButton#btnCargar:hover  { background-color: #133c4a; border-color: #00bbdd; }
QPushButton#btnCargar:pressed{ background-color: #091e28; }

/* ── Botones Play / Stop ─────────────────────────────────────────────────── */
QPushButton#btnPlay {
    background-color: #0d3020;
    border: 1.5px solid #2a8a40;
    color: #44dd66;
    font-weight: bold;
}
QPushButton#btnPlay:hover  { background-color: #114028; border-color: #44aa55; }
QPushButton#btnPlay:disabled { background: #0a1810; color: #234030; border-color: #142015; }

QPushButton#btnStop {
    background-color: #300d0d;
    border: 1.5px solid #882828;
    color: #ee4444;
    font-weight: bold;
}
QPushButton#btnStop:hover { background-color: #401010; border-color: #aa3333; }

/* ── Botón "…" (browse) ─────────────────────────────────────────────────── */
QPushButton#btnBrowse {
    background-color: #1a2235;
    border: 1px solid #2e3e5a;
    color: #7090b8;
    padding: 4px 6px;
}
QPushButton#btnBrowse:hover { background-color: #22304a; color: #90b0d8; }

/* ── Inputs ──────────────────────────────────────────────────────────────── */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background-color: #0e1422;
    border: 1px solid #2a3a5a;
    border-radius: 5px;
    padding: 5px 8px;
    color: #ccd6ed;
    font-size: 12px;
    selection-background-color: #1f4488;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #00aacc;
    background-color: #111828;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #141e30;
    border: 1px solid #2a3a5a;
    color: #ccd6ed;
    selection-background-color: #1a3a60;
    padding: 2px;
}

/* ── Barra de progreso ────────────────────────────────────────────────────── */
QProgressBar {
    border: 1px solid #2a3a5a;
    border-radius: 6px;
    background-color: #0e1422;
    text-align: center;
    color: #70aac0;
    font-size: 10px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #005a78, stop:1 #00aacc);
    border-radius: 5px;
}

/* ── Checkboxes  (el indicador con tilde se define en _CHECKBOX_EXTRA) ────── */
QCheckBox { spacing: 8px; color: #ccd6ed; font-size: 12px; }

/* ── Log (consola) ──────────────────────────────────────────────────────── */
QTextEdit {
    background-color: #0a0e1a;
    border: none;
    border-radius: 4px;
    color: #6a9aaa;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 10px;
}

/* ── Tabla ──────────────────────────────────────────────────────────────── */
QTableWidget {
    background-color: #0e1422;
    border: none;
    gridline-color: #1a2438;
    color: #b8cade;
    alternate-background-color: #121830;
    font-size: 11px;
}
QHeaderView::section {
    background-color: #182038;
    color: #5aa8c0;
    border: none;
    border-bottom: 1px solid #2a3a5a;
    padding: 7px 6px;
    font-weight: bold;
    font-size: 11px;
}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #2a3a5a;
    background-color: #161b28;
}
QTabBar::tab {
    background-color: #182038;
    color: #6080a0;
    border: 1px solid #2a3a5a;
    border-bottom: none;
    padding: 6px 16px;
    border-radius: 5px 5px 0 0;
    font-size: 11px;
}
QTabBar::tab:selected {
    background-color: #1e2840;
    color: #ccd6ed;
    border-bottom: 2px solid #00aacc;
}
QTabBar::tab:hover:!selected { background-color: #1c2a48; color: #90b0d0; }

/* ── Scrollbars ──────────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #0e1422; width: 8px; border-radius: 4px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a3a58; border-radius: 4px; min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #0e1422; height: 8px; border-radius: 4px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #2a3a58; border-radius: 4px; min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── Splitter ────────────────────────────────────────────────────────────── */
QSplitter::handle           { background: #1e2a40; }
QSplitter::handle:horizontal{ width: 4px; }
QSplitter::handle:vertical  { height: 4px; }

/* ── Labels y tooltips ──────────────────────────────────────────────────── */
QLabel { color: #a8bcd6; }
QToolTip {
    background-color: #141e30; color: #ccd6ed;
    border: 1px solid #2a4060; border-radius: 5px; padding: 5px 8px;
    font-size: 11px;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if _QT_MATERIAL:
        apply_stylesheet(app, theme="dark_teal.xml")
    else:
        app.setStyleSheet(_STYLE)
    # Indicador de checkbox con tilde real — aplica siempre (con o sin qt-material)
    app.setStyleSheet(app.styleSheet() + _CHECKBOX_EXTRA)
    ventana = AlineadorWindow()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
