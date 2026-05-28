# -*- coding: utf-8 -*-
"""
PantallaVisualizador: pantalla de visualización con polar 2D, balloon 3D
y controles de reproducción.
"""

from __future__ import annotations
import numpy as np

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QSlider, QComboBox, QPushButton, QCheckBox,
    QGroupBox, QSizePolicy,
)
from PyQt6.QtGui import QFont

from ..sesion import Sesion
from .polar_plot import PolarPlot2D
from .balloon_plot import BalloonPlot3D
from .reproductor_audio import ReproductorAudio


class PantallaVisualizador(QWidget):
    """
    Pantalla principal de visualización.

    Recibe una o dos sesiones (forte/piano) y las muestra de forma animada.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sesiones: dict[str, Sesion] = {}
        self._dinamica: str = "forte"
        self._banda_idx: int = 0
        self._frame_idx: int = 0
        self._ventana:   int = 1        # frames a promediar
        self._reproduciendo = False

        self._timer   = QTimer(self)
        self._timer.setInterval(50)     # ~20 fps
        self._timer.timeout.connect(self._avanzar_frame)

        self._audio = ReproductorAudio(self)
        self._audio.posicion_s.connect(self._sync_slider_tiempo)

        self._construir_ui()

    # ── API pública ──────────────────────────────────────────────────────────

    def agregar_sesion(self, dinamica: str, sesion: Sesion):
        self._sesiones[dinamica] = sesion
        self._combo_dinamica.addItem(dinamica) if \
            self._combo_dinamica.findText(dinamica) < 0 else None
        if dinamica == self._dinamica or len(self._sesiones) == 1:
            self._dinamica = dinamica
            self._aplicar_sesion()

    # ── Construcción UI ──────────────────────────────────────────────────────

    def _construir_ui(self):
        root = QHBoxLayout(self)
        root.setSpacing(10)

        # Columna de controles (izquierda)
        root.addWidget(self._panel_controles(), stretch=0)

        # Área de gráficos (derecha)
        graficos = QHBoxLayout()
        self._polar   = PolarPlot2D(self)
        self._balloon = BalloonPlot3D(self)
        self._polar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._balloon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        graficos.addWidget(self._polar,   stretch=1)
        graficos.addWidget(self._balloon, stretch=1)

        cont = QWidget()
        cont.setLayout(graficos)
        root.addWidget(cont, stretch=1)

    def _panel_controles(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(230)
        lay = QVBoxLayout(panel)
        lay.setSpacing(10)

        # Dinámica
        gb_din = QGroupBox("Dinámica")
        l = QVBoxLayout(gb_din)
        self._combo_dinamica = QComboBox()
        self._combo_dinamica.currentTextChanged.connect(self._on_cambio_dinamica)
        l.addWidget(self._combo_dinamica)
        lay.addWidget(gb_din)

        # Frecuencia
        gb_frec = QGroupBox("Banda de frecuencia")
        l = QVBoxLayout(gb_frec)
        self._lbl_frec = QLabel("— Hz")
        self._lbl_frec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._slider_frec = QSlider(Qt.Orientation.Horizontal)
        self._slider_frec.setMinimum(0)
        self._slider_frec.valueChanged.connect(self._on_cambio_banda)
        l.addWidget(self._lbl_frec)
        l.addWidget(self._slider_frec)
        lay.addWidget(gb_frec)

        # Tiempo
        gb_t = QGroupBox("Tiempo")
        l = QVBoxLayout(gb_t)
        self._lbl_tiempo = QLabel("0.000 s")
        self._lbl_tiempo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._slider_tiempo = QSlider(Qt.Orientation.Horizontal)
        self._slider_tiempo.setMinimum(0)
        self._slider_tiempo.valueChanged.connect(self._on_slider_tiempo)
        l.addWidget(self._lbl_tiempo)
        l.addWidget(self._slider_tiempo)
        lay.addWidget(gb_t)

        # Ventana temporal
        gb_ven = QGroupBox("Ventana temporal")
        l = QVBoxLayout(gb_ven)
        self._lbl_ventana = QLabel("50 ms")
        self._lbl_ventana.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._slider_ventana = QSlider(Qt.Orientation.Horizontal)
        self._slider_ventana.setRange(1, 20)
        self._slider_ventana.setValue(2)
        self._slider_ventana.valueChanged.connect(self._on_cambio_ventana)
        l.addWidget(self._lbl_ventana)
        l.addWidget(self._slider_ventana)
        lay.addWidget(gb_ven)

        # Suavizado
        self._chk_suavizado = QCheckBox("Suavizado gaussiano")
        self._chk_suavizado.toggled.connect(
            lambda v: self._balloon.set_suavizado(v)
        )
        lay.addWidget(self._chk_suavizado)

        # Play / Stop
        gb_play = QGroupBox("Reproducción")
        l = QHBoxLayout(gb_play)
        self._btn_play = QPushButton("▶ Play")
        self._btn_stop = QPushButton("■ Stop")
        self._btn_play.clicked.connect(self._on_play)
        self._btn_stop.clicked.connect(self._on_stop)
        l.addWidget(self._btn_play)
        l.addWidget(self._btn_stop)
        lay.addWidget(gb_play)

        lay.addStretch()

        # Info sesión
        self._lbl_info = QLabel("")
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet("color: gray; font-size: 10px;")
        lay.addWidget(self._lbl_info)

        return panel

    # ── Aplicar sesión ────────────────────────────────────────────────────────

    def _aplicar_sesion(self):
        sesion = self._sesiones.get(self._dinamica)
        if sesion is None:
            return

        self._polar.set_angulos(sesion.angulos_array)
        self._balloon.set_angulos(sesion.angulos_array, sesion.angulos_mesa)

        # Sliders de frecuencia y tiempo
        self._slider_frec.setMaximum(sesion.n_bandas - 1)
        self._slider_frec.setValue(0)
        self._banda_idx = 0

        onset = sesion.onset_frame
        self._slider_tiempo.setMaximum(sesion.n_frames - 1)
        self._slider_tiempo.blockSignals(True)
        self._slider_tiempo.setValue(onset)
        self._slider_tiempo.blockSignals(False)
        self._frame_idx = onset

        self._actualizar_label_frec()
        self._actualizar_label_tiempo()
        self._actualizar_graficos()

        # Audio de referencia
        if sesion.audio_ref is not None:
            self._audio.cargar(sesion.audio_ref, sesion.sr_ref)

        # Info
        self._lbl_info.setText(
            f"{sesion.n_mics} mics × {sesion.n_angulos} ángulos\n"
            f"{sesion.n_bandas} bandas · {sesion.n_frames} frames\n"
            f"dur. {sesion.dur_comun_s:.2f} s · sr={sesion.sr} Hz"
        )

    # ── Actualización de gráficos ─────────────────────────────────────────────

    def _actualizar_graficos(self):
        sesion = self._sesiones.get(self._dinamica)
        if sesion is None or sesion.tensor_spl is None:
            return

        spl_mat = sesion.spl_frame(self._banda_idx, self._frame_idx, self._ventana)
        # spl_mat: (n_mics, n_angulos)

        # Polar: promedio sobre ángulos de mesa → (n_mics,)
        spl_polar = np.mean(spl_mat, axis=1)
        self._polar.actualizar(spl_polar)

        # Balloon: matriz completa (n_mics, n_angulos)
        self._balloon.actualizar(spl_mat)

    # ── Slots de controles ────────────────────────────────────────────────────

    def _on_cambio_dinamica(self, texto: str):
        self._on_stop()
        self._dinamica = texto
        self._aplicar_sesion()

    def _on_cambio_banda(self, valor: int):
        self._banda_idx = valor
        self._actualizar_label_frec()
        self._actualizar_graficos()

    def _on_slider_tiempo(self, valor: int):
        self._frame_idx = valor
        self._actualizar_label_tiempo()
        self._actualizar_graficos()
        sesion = self._sesiones.get(self._dinamica)
        if sesion:
            self._audio.seek(valor * sesion.hop_size / max(sesion.sr, 1))

    def _on_cambio_ventana(self, valor: int):
        self._ventana = valor
        sesion = self._sesiones.get(self._dinamica)
        if sesion:
            ms = valor * sesion.hop_size / max(sesion.sr, 1) * 1000
            self._lbl_ventana.setText(f"{ms:.0f} ms")
        self._actualizar_graficos()

    def _on_play(self):
        if self._reproduciendo:
            return
        self._reproduciendo = True
        sesion = self._sesiones.get(self._dinamica)
        if sesion and sesion.audio_ref is not None:
            t0 = self._frame_idx * sesion.hop_size / max(sesion.sr, 1)
            self._audio.reproducir(desde_s=t0)
        self._timer.start()

    def _on_stop(self):
        self._reproduciendo = False
        self._timer.stop()
        self._audio.detener()

    def _avanzar_frame(self):
        sesion = self._sesiones.get(self._dinamica)
        if sesion is None:
            return
        self._frame_idx = min(self._frame_idx + 1, sesion.n_frames - 1)
        self._slider_tiempo.blockSignals(True)
        self._slider_tiempo.setValue(self._frame_idx)
        self._slider_tiempo.blockSignals(False)
        self._actualizar_label_tiempo()
        self._actualizar_graficos()
        if self._frame_idx >= sesion.n_frames - 1:
            self._on_stop()

    def _sync_slider_tiempo(self, tiempo_s: float):
        sesion = self._sesiones.get(self._dinamica)
        if sesion is None:
            return
        frame = int(tiempo_s * sesion.sr / max(sesion.hop_size, 1))
        frame = min(frame, sesion.n_frames - 1)
        if abs(frame - self._frame_idx) > 1:
            self._frame_idx = frame
            self._slider_tiempo.blockSignals(True)
            self._slider_tiempo.setValue(frame)
            self._slider_tiempo.blockSignals(False)
            self._actualizar_label_tiempo()
            self._actualizar_graficos()

    # ── Labels ────────────────────────────────────────────────────────────────

    def _actualizar_label_frec(self):
        sesion = self._sesiones.get(self._dinamica)
        if sesion and sesion.bandas_hz:
            hz = sesion.bandas_hz[self._banda_idx]
            self._lbl_frec.setText(f"{hz:.0f} Hz")

    def _actualizar_label_tiempo(self):
        sesion = self._sesiones.get(self._dinamica)
        if sesion:
            t = self._frame_idx * sesion.hop_size / max(sesion.sr, 1)
            self._lbl_tiempo.setText(f"{t:.3f} s")
