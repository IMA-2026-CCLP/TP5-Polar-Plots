# -*- coding: utf-8 -*-
"""
Clase Sesion: contenedor del tensor SPL y metadatos de una dinámica.
Soporta guardado y carga desde .npy + .json.
"""

import json
from pathlib import Path

import numpy as np


class Sesion:
    """
    Encapsula el resultado del pipeline de preprocesamiento para una dinámica.

    Atributos
    ---------
    tensor_spl : np.ndarray  shape (n_mics, n_angulos, n_bandas, n_frames)
    metadatos  : dict        sr, angulos_array, angulos_mesa, bandas, dur_comun_s, etc.
    audio_ref  : np.ndarray  señal del mic de referencia (ángulo 90°)
    sr_ref     : int
    """

    def __init__(self):
        self.tensor_spl: np.ndarray | None = None
        self.metadatos:  dict               = {}
        self.audio_ref:  np.ndarray | None  = None
        self.sr_ref:     int | None         = None

    # ── Propiedades de conveniencia ─────────────────────────────────────────

    @property
    def n_mics(self)    -> int: return self.metadatos.get("n_mics", 0)
    @property
    def n_angulos(self) -> int: return self.metadatos.get("n_angulos", 0)
    @property
    def n_bandas(self)  -> int: return self.metadatos.get("n_bandas", 0)
    @property
    def n_frames(self)  -> int: return self.metadatos.get("n_frames", 0)
    @property
    def bandas_hz(self) -> list[float]:
        return self.metadatos.get("bandas_hz", [])
    @property
    def angulos_mesa(self) -> list[int]:
        return self.metadatos.get("angulos_mesa", [])
    @property
    def angulos_array(self) -> list[int]:
        return self.metadatos.get("angulos_array", [])
    @property
    def dur_comun_s(self) -> float:
        return self.metadatos.get("dur_comun_s", 0.0)
    @property
    def hop_size(self) -> int:
        return self.metadatos.get("hop_size", 1)
    @property
    def sr(self) -> int:
        return self.metadatos.get("sr", 0)

    @property
    def rollon_ms(self) -> float:
        return self.metadatos.get("rollon_ms", 500.0)

    @property
    def calibracion_db(self) -> float:
        return self.metadatos.get("calibracion_db", 97.0)

    @property
    def onset_frame(self) -> int:
        """Primer frame en la región activa (después del roll-on de silencio)."""
        rollon_n = int(self.rollon_ms / 1000 * self.sr)
        frame_idx = rollon_n // max(self.hop_size, 1)
        return min(frame_idx, max(0, self.n_frames - 1))

    # ── SPL instantáneo ────────────────────────────────────────────────────

    def spl_frame(self, banda_idx: int, frame_idx: int,
                  ventana: int = 1) -> np.ndarray:
        """
        Devuelve la matriz SPL (n_mics, n_angulos) para un instante dado,
        promediando `ventana` frames centrados en frame_idx.

        Sin loops Python — todo operación numpy.
        """
        t = frame_idx
        w = ventana
        t0 = max(0, t - w // 2)
        t1 = min(self.n_frames, t + w // 2 + 1)

        seg     = self.tensor_spl[:, :, banda_idx, t0:t1]   # (n_m, n_a, W)
        energia = np.mean(10 ** (seg / 10), axis=2)          # (n_m, n_a)
        return (10 * np.log10(energia + 1e-10)).astype(np.float32)

    # ── Persistencia ────────────────────────────────────────────────────────

    def guardar(self, carpeta: str | Path, dinamica: str):
        """Guarda tensor .npy + metadatos .json."""
        carpeta = Path(carpeta)
        carpeta.mkdir(parents=True, exist_ok=True)
        np.save(str(carpeta / f"tensor_{dinamica}.npy"), self.tensor_spl)
        if self.audio_ref is not None:
            np.save(str(carpeta / f"audio_ref_{dinamica}.npy"), self.audio_ref)
        meta = dict(self.metadatos)
        meta["sr_ref"] = self.sr_ref
        with open(carpeta / f"sesion_{dinamica}.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    @classmethod
    def cargar(cls, carpeta: str | Path, dinamica: str) -> "Sesion":
        """Carga sesión desde .npy + .json. Lanza FileNotFoundError si falta."""
        carpeta = Path(carpeta)
        sesion  = cls()
        sesion.tensor_spl = np.load(str(carpeta / f"tensor_{dinamica}.npy"))
        ref_path = carpeta / f"audio_ref_{dinamica}.npy"
        if ref_path.exists():
            sesion.audio_ref = np.load(str(ref_path))
        with open(carpeta / f"sesion_{dinamica}.json", encoding="utf-8") as f:
            meta = json.load(f)
        sesion.sr_ref   = meta.pop("sr_ref", None)
        sesion.metadatos = meta
        return sesion

    @staticmethod
    def existe(carpeta: str | Path, dinamica: str) -> bool:
        carpeta = Path(carpeta)
        return (
            (carpeta / f"tensor_{dinamica}.npy").exists()
            and (carpeta / f"sesion_{dinamica}.json").exists()
        )
