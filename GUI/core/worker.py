"""
core/worker.py — QThread para procesamiento en background
"""
import traceback
import numpy as np
from typing import Callable, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

from PyQt6.QtCore import QThread, pyqtSignal

from .scanner import AudioFile
from .data_store import ISO_BANDS_OCTAVE, save_polar, ISO_BANDS_HZ


class ProcessWorker(QThread):
    """
    Hilo de procesamiento que itera sobre los audios,
    llama a process_audio() y arma el array 3D de niveles.
    """

    # ── Señales ──────────────────────────────────────────────────────────────
    progress = pyqtSignal(int, int, str)   # (actual, total, filename)
    log_msg  = pyqtSignal(str)             # mensaje de log
    finished = pyqtSignal(dict)            # datos resultantes
    error    = pyqtSignal(str)             # mensaje de error

    def __init__(
        self,
        files: List[AudioFile],
        process_fn: Callable,
        output_path: str,
        band_width: str,
        selected_bands: Optional[List[float]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.files = files
        self.process_fn = process_fn
        self.output_path = output_path
        self.band_width = 1 if band_width == "Por Octava" else 3
        self.selected_bands = selected_bands  # None = todas las bandas
        self._cancelled = False
        # print(f'[ProcessWorker] Inicializado con {self.band_width} ancho de octava, ')

    def cancel(self):
        self._cancelled = True

    # ── QThread.run ──────────────────────────────────────────────────────────

    def run(self):
        try:
            result = self._process_all()
            if not self._cancelled:
                self.finished.emit(result)
        except Exception:
            self.error.emit(traceback.format_exc())

    # ── Procesamiento ────────────────────────────────────────────────────────

    def _process_all(self) -> dict:
        files = self.files
        n = len(files)

        # Grilla de ángulos únicos
        azimuths   = sorted(set(f.azimuth   for f in files))
        elevations = sorted(set(f.elevation for f in files))
        az_idx = {v: i for i, v in enumerate(azimuths)}
        el_idx = {v: i for i, v in enumerate(elevations)}

        n_az = len(azimuths)
        n_el = len(elevations)

        self.log_msg.emit(
            f"Grilla: {n_az} azimuts × {n_el} elevaciones = {n_az*n_el} puntos"
        )
        self.log_msg.emit(f"Archivos a procesar: {n}")

        # ── Procesar primer archivo para determinar bandas ────────────────
        self.log_msg.emit(f"[1/{n}] {files[0].filename}")
        first_result = self.process_fn(files[0].path, self.band_width, self.selected_bands)

        if isinstance(first_result, dict):
            bands = sorted(first_result.keys())
            def extract(res): return [res[b] for b in bands]
        else:
            first_result = list(first_result)
            n_b = len(first_result)
            if self.band_width == 1 and n_b <= len(ISO_BANDS_OCTAVE):
                bands = ISO_BANDS_OCTAVE[:n_b]
            elif self.band_width == 3 and n_b <= len(ISO_BANDS_HZ):
                bands = ISO_BANDS_HZ[:n_b]
            else:
                bands = list(range(n_b))
            def extract(res): return list(res)

        n_bands = len(bands)
        self.log_msg.emit(
            f"Bandas detectadas: {n_bands}  "
            f"({bands[0]} Hz → {bands[-1]} Hz)"
        )

        if self.selected_bands is not None and len(self.selected_bands) > 0:
            self.log_msg.emit(
                f"Procesando {n_bands} bandas seleccionadas "
            )
        else:
            self.log_msg.emit(f"Procesando todas las bandas disponibles")

        # ── Array de resultados (NaN = sin dato) ─────────────────────────
        levels = np.full((n_az, n_el, n_bands), np.nan, dtype=np.float32)

        # Guardar primer resultado
        ai = az_idx[files[0].azimuth]
        ei = el_idx[files[0].elevation]
        levels[ai, ei, :] = extract(first_result)
        self.progress.emit(1, n, files[0].filename)

        # Procesamiento paralelo con ThreadPoolExecutor
        N_WORKERS = min(os.cpu_count() or 4, 4)
        
        with ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
            future_to_file = {
                executor.submit(self.process_fn, af.path, self.band_width, self.selected_bands): (i, af)
                for i, af in enumerate(files[1:], start=2)
            }
            
            completed = 0
            for future in as_completed(future_to_file):
                if self._cancelled:
                    self.log_msg.emit("Procesamiento cancelado por el usuario.")
                    break
                
                idx, af = future_to_file[future]
                try:
                    res = future.result()
                    ai = az_idx[af.azimuth]
                    ei = el_idx[af.elevation]
                    levels[ai, ei, :] = extract(res)
                except Exception as e:
                    self.log_msg.emit(f"Error en {af.filename}: {e}")
                
                completed += 1
                self.progress.emit(completed + 1, n, af.filename)

        # ── Guardar NPZ ───────────────────────────────────────────────────
        save_polar(
            self.output_path,
            levels=levels,
            azimuths=np.array(azimuths, dtype=float),
            elevations=np.array(elevations, dtype=float),
            bands=np.array(bands, dtype=float),
            metadata={'source_files': n, 'cancelled': self._cancelled},
        )
        self.log_msg.emit(f"✓ Datos guardados en: {self.output_path}")

        return {
            'levels': levels,
            'azimuths': np.array(azimuths, dtype=float),
            'elevations': np.array(elevations, dtype=float),
            'bands': np.array(bands, dtype=float),
        }
