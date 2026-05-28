# -*- coding: utf-8 -*-
"""
Preprocesador: ejecuta el pipeline de 9 pasos definido en la SPEC.

Corre en un QThread para no bloquear la GUI. Comunica progreso y logs
mediante signals de Qt.

Pasos:
  1  Descubrimiento de archivos
  2  Lectura de WAVs
  3  Filtro FIR pasa altos
  4  Alineación temporal GCC-PHAT (respecto al mic de referencia)
  5  Detección de onset y offset (en mic de referencia)
  6  Igualación de duración
  7  Cálculo de STFT
  8  Cálculo de SPL por banda de 1/3 oct
  9  Guardado de sesión
"""

from __future__ import annotations

import numpy as np
from pathlib import Path
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from .sesion import Sesion
from .utils.audio_io import LectorWAV, Descubridor, resamplear
from .utils.dsp import FiltroPasaAltosFIR, AlineadorGCCPHAT, DetectorOnsetOffset
from .utils.tercio_octava import CalculadorSPL


# ═══════════════════════════════════════════════════════════════
# Worker (corre en QThread)
# ═══════════════════════════════════════════════════════════════

class PreprocesadorWorker(QObject):
    """
    Ejecuta el pipeline en un hilo separado.

    Signals
    -------
    progreso(int)          : 0–100
    log(str)               : mensaje con timestamp implícito (lo agrega la GUI)
    terminado(Sesion)      : sesión lista
    error(str)             : descripción del error
    """

    progreso  = pyqtSignal(int)
    log       = pyqtSignal(str)
    terminado = pyqtSignal(object)   # Sesion
    error     = pyqtSignal(str)

    def __init__(
        self,
        carpeta:          str,
        dinamica:         str,
        template_mics:    str,
        template_refs:    str,
        n_mics:           int,
        angulos_array:    list[int],
        angulos_mesa:     list[int],
        carpeta_sesion:   str,
        fc_hz:            float = 100.0,
        ripple_db:        float = 60.0,
        width_hz:         float = 40.0,
        ruido_seg:        float = 3.0,
        margen_db:        float = 12.0,
        rollon_ms:        float = 500.0,
        rolloff_ms:       float = 500.0,
        frame_ms:         float = 10.0,
        max_delay_seg:    float = 0.05,
        calibracion_db:   float = 97.0,
        guardar_procesados: bool = False,
    ):
        super().__init__()
        self.carpeta        = Path(carpeta)
        self.dinamica       = dinamica
        self.template_mics  = template_mics
        self.template_refs  = template_refs
        self.n_mics         = n_mics
        self.angulos_array  = angulos_array
        self.angulos_mesa   = angulos_mesa
        self.carpeta_sesion = Path(carpeta_sesion)
        self.fc_hz          = fc_hz
        self.ripple_db      = ripple_db
        self.width_hz       = width_hz
        self.ruido_seg      = ruido_seg
        self.margen_db      = margen_db
        self.rollon_ms      = rollon_ms
        self.rolloff_ms     = rolloff_ms
        self.frame_ms           = frame_ms
        self.max_delay_seg      = max_delay_seg
        self.calibracion_db     = calibracion_db
        self.guardar_procesados = guardar_procesados
        self._cancelado         = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        try:
            sesion = self._pipeline()
            if not self._cancelado:
                self.terminado.emit(sesion)
        except Exception as exc:
            self.error.emit(str(exc))

    # ── Pipeline ─────────────────────────────────────────────────────────────

    def _pipeline(self) -> Sesion:
        self._log(f"=== Iniciando pipeline '{self.dinamica}' ===")
        self._log(f"Carpeta: {self.carpeta}")

        # ── PASO 1: Descubrimiento ────────────────────────────────────────
        self._log("Paso 1 — Descubrimiento de archivos")
        desc = Descubridor(self.template_mics, self.template_refs)

        # Mostrar patrones compilados para diagnóstico
        self._log(f"  Patrón mics: {desc.patron_mics()}")
        self._log(f"  Patrón refs: {desc.patron_refs()}")

        mics_map, refs_map, ignorados = desc.descubrir(self.carpeta, self.dinamica)

        self._log(f"  WAVs de micrófonos reconocidos: {len(mics_map)}")
        self._log(f"  WAVs de referencias reconocidos: {len(refs_map)}")
        self._log(f"  Ignorados: {len(ignorados)}")

        # Mostrar los primeros ignorados para diagnóstico
        for n in ignorados[:15]:
            self._log(f"    [ignorado] {n}")

        # Si no hay refs, mostrar qué archivos podrían ser refs
        if not refs_map and ignorados:
            candidatos = [n for n in ignorados if "ref" in n.lower()]
            if candidatos:
                self._log(f"  ¿Estos son tus archivos de referencia?")
                for n in candidatos[:5]:
                    self._log(f"    → {n}")
                self._log(f"  Ajustá la 'Plantilla referencias' en la configuración.")

        if not mics_map:
            raise RuntimeError("No se encontraron archivos de micrófonos válidos.")
        if not refs_map:
            raise RuntimeError("No se encontraron archivos de referencia válidos.")

        self._progreso(8)
        if self._cancelado: return None

        # ── PASO 2: Lectura de WAVs ───────────────────────────────────────
        self._log("Paso 2 — Lectura de WAVs")

        # Paso 2a: detectar SR de los mics cargando el primero
        import soundfile as _sf
        primer_mic_path = sorted(mics_map.items())[0][1]
        _, sr_mics = _sf.read(str(primer_mic_path), frames=1, dtype="float32")
        self._log(f"  SR micrófonos: {sr_mics} Hz")

        # Paso 2b: cargar mics con el SR nativo (todos deberían ser iguales)
        lector_mics = LectorWAV(sr_objetivo=sr_mics)
        senales: dict[int, dict[int, np.ndarray]] = {}
        total = len(mics_map)
        for i, ((mic, ang), path) in enumerate(sorted(mics_map.items())):
            sig, _ = lector_mics.cargar(path)
            senales.setdefault(ang, {})[mic] = sig
            if i % 20 == 0:
                self._log(f"  Cargados {i+1}/{total} ...")
        self._log(f"  Total mics cargados: {total}")

        # Paso 2c: cargar refs resampleando al SR de los mics si es necesario
        lector_refs = LectorWAV(sr_objetivo=sr_mics)
        refs: dict[int, np.ndarray] = {}
        for ang in sorted(refs_map):
            sig, sr_sal, sr_nat = lector_refs.cargar_detectar_sr(refs_map[ang])
            refs[ang] = sig
            resamp_str = f"  [resampleado {sr_nat}→{sr_mics} Hz]" if sr_nat != sr_mics else ""
            self._log(f"  ref {ang:>4}°  {len(sig)/sr_mics:.2f}s  sr={sr_nat} Hz{resamp_str}")

        sr = sr_mics
        self._log(f"  SR común final: {sr} Hz")
        self._progreso(20)
        if self._cancelado: return None

        # ── PASO 3: Filtro pasa altos ─────────────────────────────────────
        self._log(f"Paso 3 — Filtro pasa altos Butterworth (fc={self.fc_hz} Hz)")
        fir = FiltroPasaAltosFIR(self.fc_hz, self.ripple_db, self.width_hz)
        orden, _ = fir.preparar(sr)
        self._log(f"  Orden efectivo: {orden}  (sosfiltfilt, fase cero, delay neto = 0)")

        refs    = {a: fir.aplicar(s, sr) for a, s in refs.items()}
        senales = {
            ang: {mic: fir.aplicar(s, sr) for mic, s in mics.items()}
            for ang, mics in senales.items()
        }
        self._progreso(35)
        if self._cancelado: return None

        # ── PASO 4: Alineación GCC-PHAT ──────────────────────────────────
        self._log("Paso 4 — Alineación temporal GCC-PHAT")
        alineador = AlineadorGCCPHAT(self.max_delay_seg)

        for ang in sorted(senales):
            if ang not in refs:
                self._log(f"  [SKIP] ángulo {ang}°: sin mic de referencia")
                continue
            ref = refs[ang]
            largo = len(ref)
            mics_ang = senales[ang]
            for mic, sig in sorted(mics_ang.items()):
                largo_min = min(len(sig), largo)
                delay = alineador.delay_muestras(sig[:largo_min], ref[:largo_min], sr)
                mics_ang[mic] = alineador.alinear(sig, delay, largo_min)
            # También recortar la referencia al mínimo común
            refs[ang] = ref[:largo]
            self._log(f"  Ángulo {ang:>4}°: {len(mics_ang)} mics alineados")

        self._progreso(50)
        if self._cancelado: return None

        # ── PASO 5: Detección de onset y offset ──────────────────────────
        self._log("Paso 5 — Detección de onset/offset")
        detector = DetectorOnsetOffset(
            ruido_seg=self.ruido_seg,
            margen_db=self.margen_db,
            rollon_ms=self.rollon_ms,
            rolloff_ms=self.rolloff_ms,
        )

        rangos: dict[int, tuple[int, int]] = {}
        for ang in sorted(refs):
            start, stop, piso, umbral = detector.detectar(refs[ang], sr)
            rangos[ang] = (start, stop)
            self._log(
                f"  {ang:>4}°  piso={piso:.1f} dB  umbral={umbral:.1f} dB  "
                f"onset={start/sr:.2f}s  offset={stop/sr:.2f}s  "
                f"duración={( stop-start)/sr:.2f}s"
            )

        # ── PASO 6: Igualación de duración ───────────────────────────────
        self._log("Paso 6 — Igualación de duración")
        dur_comun = min(stop - start for start, stop in rangos.values())
        dur_s     = dur_comun / sr
        self._log(f"  Duración común: {dur_s:.3f} s ({dur_comun} muestras)")

        # Recortar señales al rango de cada ángulo, luego al mínimo común
        for ang in list(senales):
            if ang not in rangos:
                del senales[ang]
                continue
            start, _ = rangos[ang]
            refs[ang] = refs[ang][start:start + dur_comun]
            mics_ang  = senales[ang]
            for mic in mics_ang:
                mics_ang[mic] = mics_ang[mic][start:start + dur_comun]

        self._progreso(60)
        if self._cancelado: return None

        # ── GUARDADO DE AUDIO PROCESADO (opcional) ───────────────────────
        if self.guardar_procesados:
            self._guardar_audio_procesado(senales, refs, sr)
        if self._cancelado: return None

        # ── PASO 7 & 8: STFT + SPL por bandas ───────────────────────────
        self._log("Paso 7 — Cálculo de STFT")
        self._log("Paso 8 — SPL por bandas de 1/3 oct")

        # Tamaño de frame como potencia de 2 más cercana a frame_ms
        frame_size = _siguiente_potencia_2(int(sr * self.frame_ms / 1000))
        hop_size   = frame_size // 4    # 75% overlap
        ventana    = np.hanning(frame_size).astype(np.float32)

        calc_spl = CalculadorSPL(sr, frame_size)
        n_bandas = calc_spl.n_bandas
        bandas_hz = calc_spl.f_centro.tolist()
        self._log(f"  frame={frame_size} muestras ({frame_size/sr*1000:.1f} ms)  "
                  f"hop={hop_size}  bandas={n_bandas}")

        angulos_mesa_disp  = sorted(senales.keys())
        n_angulos          = len(angulos_mesa_disp)
        mics_disp          = sorted(next(iter(senales.values())).keys())

        # Convertir números de mic a ángulos reales en grados.
        # mic k → self.angulos_array[k-1]  (mic 1 = 0°, mic 2 = 10°, etc.)
        angulos_array_disp = [
            self.angulos_array[mic - 1]
            for mic in mics_disp
            if mic - 1 < len(self.angulos_array)
        ]

        # Calcular n_frames estimado
        n_frames = (dur_comun - frame_size) // hop_size + 1

        # Tensor acumulador
        tensor = np.zeros(
            (len(angulos_array_disp), n_angulos, n_bandas, n_frames),
            dtype=np.float32
        )

        total_ang = len(angulos_mesa_disp)
        for ai, ang_mesa in enumerate(angulos_mesa_disp):
            mics_ang = senales[ang_mesa]
            for mi, mic in enumerate(mics_disp):
                sig = mics_ang.get(mic)
                if sig is None:
                    self._log(f"  [WARN] falta mic {mic} en ángulo {ang_mesa}°")
                    continue
                stft_mag = _calcular_stft_mag(sig, frame_size, hop_size, ventana)
                # stft_mag: (n_bins, n_frames_real)
                nf = min(stft_mag.shape[1], n_frames)
                spl = calc_spl.calcular_tensor(stft_mag[:, :nf])  # (n_bandas, nf)
                spl = spl + self.calibracion_db   # dBFS → dBSPL
                tensor[mi, ai, :, :nf] = spl

            pct = 60 + int(35 * (ai + 1) / total_ang)
            self._progreso(pct)
            self._log(f"  Ángulo mesa {ang_mesa:>4}° ({ai+1}/{total_ang})")
            if self._cancelado: return None

        # ── PASO 9: Guardar sesión ────────────────────────────────────────
        self._log("Paso 9 — Guardando sesión")
        sesion = Sesion()
        sesion.tensor_spl = tensor
        sesion.metadatos  = {
            "dinamica":      self.dinamica,
            "sr":            sr,
            "n_mics":        len(angulos_array_disp),
            "n_angulos":     n_angulos,
            "n_bandas":      n_bandas,
            "n_frames":      n_frames,
            "bandas_hz":     bandas_hz,
            "angulos_mesa":  angulos_mesa_disp,
            "angulos_array": angulos_array_disp,
            "dur_comun_s":   dur_s,
            "frame_size":    frame_size,
            "hop_size":      hop_size,
            "frame_ms":        self.frame_ms,
            "rollon_ms":       self.rollon_ms,
            "calibracion_db":  self.calibracion_db,
        }

        # Audio de referencia (ángulo 90° si existe)
        ang_ref = 90
        if ang_ref not in refs and refs:
            ang_ref = min(refs, key=lambda a: abs(a - 90))
        if ang_ref in refs:
            sesion.audio_ref = refs[ang_ref]
            sesion.sr_ref    = sr

        sesion.guardar(self.carpeta_sesion, self.dinamica)
        mb = tensor.nbytes / 1e6
        self._log(f"  Tensor guardado: {tensor.shape}  {mb:.1f} MB")
        self._log(f"  Carpeta sesión: {self.carpeta_sesion}")
        self._progreso(100)
        self._log("=== Pipeline completado ===")
        return sesion

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _guardar_audio_procesado(
        self,
        senales: dict[int, dict[int, np.ndarray]],
        refs: dict[int, np.ndarray],
        sr: int,
    ):
        """
        Guarda los WAVs filtrados, alineados y recortados en:
            <carpeta_media>/_procesados/<dinamica>/

        Formato: float32, mismo SR que los mics.
        """
        import soundfile as sf

        carpeta_proc = self.carpeta / "_procesados" / self.dinamica
        carpeta_proc.mkdir(parents=True, exist_ok=True)
        self._log(f"Guardando audio procesado en: {carpeta_proc}")

        total = sum(len(mics) for mics in senales.values()) + len(refs)
        guardados = 0

        for ang_mesa in sorted(senales):
            for mic in sorted(senales[ang_mesa]):
                sig  = senales[ang_mesa][mic]
                fname = f"mic_{mic:02d}_ang_{self.dinamica}_{ang_mesa:03d}_proc.wav"
                sf.write(str(carpeta_proc / fname), sig, sr, subtype="FLOAT")
                guardados += 1
                if guardados % 30 == 0:
                    self._log(f"  Guardados {guardados}/{total} ...")

            if ang_mesa in refs:
                fname = f"mic_ref_ang_{self.dinamica}_{ang_mesa:03d}_proc.wav"
                sf.write(str(carpeta_proc / fname), refs[ang_mesa], sr, subtype="FLOAT")
                guardados += 1

        self._log(f"  {guardados} archivos guardados.")

    def _log(self, msg: str):
        self.log.emit(msg)

    def _progreso(self, pct: int):
        self.progreso.emit(pct)


# ═══════════════════════════════════════════════════════════════
# Funciones auxiliares (sin estado)
# ═══════════════════════════════════════════════════════════════

def _siguiente_potencia_2(n: int) -> int:
    return int(2 ** np.ceil(np.log2(max(n, 1))))


def _calcular_stft_mag(sig: np.ndarray, frame_size: int,
                        hop_size: int, ventana: np.ndarray) -> np.ndarray:
    """
    STFT de `sig` con ventana Hann y hop_size dado.

    Returns
    -------
    mag : np.ndarray  shape (n_bins, n_frames)
    """
    n_frames = (len(sig) - frame_size) // hop_size + 1
    n_bins   = frame_size // 2 + 1
    mag      = np.empty((n_bins, n_frames), dtype=np.float32)

    for i in range(n_frames):
        inicio = i * hop_size
        frame  = sig[inicio:inicio + frame_size] * ventana
        espectro = np.fft.rfft(frame, n=frame_size)
        mag[:, i] = np.abs(espectro).astype(np.float32)

    return mag


# ═══════════════════════════════════════════════════════════════
# Clase pública: Preprocesador (gestiona el QThread)
# ═══════════════════════════════════════════════════════════════

class Preprocesador(QObject):
    """
    Interfaz principal para lanzar el pipeline desde la GUI.
    Crea y gestiona el QThread + PreprocesadorWorker.
    """

    progreso  = pyqtSignal(int)
    log       = pyqtSignal(str)
    terminado = pyqtSignal(object)   # Sesion
    error     = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None  = None
        self._worker: PreprocesadorWorker | None = None

    def iniciar(self, **kwargs):
        """Lanza el pipeline. Todos los kwargs se pasan al PreprocesadorWorker."""
        if self._thread and self._thread.isRunning():
            return

        self._thread = QThread()
        self._worker = PreprocesadorWorker(**kwargs)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progreso.connect(self.progreso)
        self._worker.log.connect(self.log)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def cancelar(self):
        if self._worker:
            self._worker.cancelar()

    def _on_terminado(self, sesion):
        self._thread.quit()
        self.terminado.emit(sesion)

    def _on_error(self, msg: str):
        self._thread.quit()
        self.error.emit(msg)
