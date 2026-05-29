# Especificación Técnica — Analizador de Directividad Vocal
## Versión 1.0

---

## 1. Contexto del proyecto

Software de análisis y visualización del patrón de directividad de una fuente
sonora biomecánica (voz cantada femenina), medida con un array semicircular de
micrófonos y una mesa giratoria.

### Configuración de medición
- **Fuente:** cantante femenina, escala mayor de F4 (349 Hz) a F5 (698 Hz)
- **Array:** 19 micrófonos en semicírculo de 0° a 180°, equiespaciados 10°
- **Mesa giratoria:** Outline, barrido de 0° a 180° cada 10° → 19 posiciones
- **Micrófono de referencia:** 1 mic a 1m de la boca, rota junto con la mesa
- **Dinámicas medidas:** forte y piano
- **Total de archivos:** ~380 WAVs por dinámica (19 mics × 19 ángulos + 19 refs)

### Observaciones importantes
- Las mediciones de 0°, 10° y 20° se perdieron por error de configuración
  en Reaper. Se reemplazan por simetría vocal con las mediciones de 180°,
  170° y 160° respectivamente, invirtiendo el orden de los micrófonos
  (mic_k ↔ mic_(20-k)).
- El micrófono 9 (80°) no grabó señal válida. Se interpola en el dominio
  temporal usando GCC-PHAT entre mic 8 (70°) y mic 10 (90°).
- Todos los micrófonos están calibrados a 94 dB SPL.

---

## 2. Estructura de archivos

### Nomenclatura (configurable por el usuario en la GUI)
```
Mediciones:  mic_{MIC}_ang_{DIN}_{ANG}.wav
Referencias: mic_ref_ang_{DIN}_{ANG}.wav

Donde:
  {MIC} → número de micrófono (1 a 19)
  {DIN} → dinámica (forte, piano)
  {ANG} → ángulo de mesa giratoria (0, 10, 20, ..., 180)
```

### Estructura de directorios recomendada
```
forte/
  mic_1_ang_forte_0.wav
  mic_1_ang_forte_10.wav
  ...
  mic_19_ang_forte_180.wav
  mic_ref_ang_forte_0.wav
  ...
  mic_ref_ang_forte_180.wav

piano/
  mic_1_ang_piano_0.wav
  ...
  mic_ref_ang_piano_180.wav
```

Todo en una sola carpeta por dinámica, sin subcarpetas, para maximizar
velocidad de lectura del filesystem. El programa distingue mediciones de
referencias por la plantilla de nombre.

---

## 3. Arquitectura del software

### Stack tecnológico
```
PyQt6          → ventana principal, controles, layout
matplotlib     → polar 2D animado (embebido en Qt)
pyqtgraph      → balloon 3D OpenGL animado (embebido en Qt)
numpy          → tensor SPL y operaciones matriciales
soundfile      → lectura de WAVs
scipy          → filtro FIR, STFT, interpolación spline
pyinstaller    → empaquetado en .exe (Windows) y .app (Mac)
```

### Instalación de dependencias
```bash
pip install PyQt6 matplotlib pyqtgraph numpy soundfile scipy pyinstaller
```

### Estructura de clases (OOP)

```
MainApp
├── PantallaCarga
│   ├── ConfiguracionArray
│   ├── ConfiguracionNomenclatura
│   ├── ConfiguracionPreprocesamiento
│   ├── BarraProgreso
│   └── PanelLog
├── Preprocesador
│   ├── LectorWAV
│   ├── FiltroPasaAltosFIR
│   ├── AlineadorGCCPHAT
│   ├── DetectorOnsetOffset
│   └── CalculadorSTFT
├── Sesion
│   ├── tensor_spl         # (n_mics, n_angulos, n_bandas, n_frames) float32
│   ├── metadatos          # sr, duracion, angulos, bandas, etc.
│   └── audio_referencia   # señal WAV del mic de referencia
├── PantallaVisualizador
│   ├── ControlDinamica
│   ├── SliderFrecuencia
│   ├── SliderTiempo
│   ├── SliderVentana
│   ├── CheckboxSuavizado
│   ├── BotonesPlayStop
│   ├── PolarPlot2D
│   ├── BalloonPlot3D
│   └── ReproductorAudio
```

---

## 4. Pipeline de preprocesamiento

Se ejecuta una sola vez al presionar "Procesar". Todo en RAM después de
la carga inicial — nunca más se accede al disco durante la visualización.

```
Para cada dinámica (forte / piano):

  PASO 1 — Descubrimiento de archivos
    → rglob('*.wav') en la carpeta raíz
    → parsear nombre con plantilla del usuario usando regex
    → extraer MIC, ANG, DIN de cada archivo
    → separar mediciones de referencias
    → loguear: "Encontrados X WAVs reconocidos, Y ignorados"

  PASO 2 — Lectura de WAVs
    → cargar todos los WAVs con soundfile
    → convertir a mono float32
    → verificar sample rate consistente entre archivos
    → loguear sr, duración, canales de cada archivo

  PASO 3 — Filtro FIR pasa altos
    → fc = 100 Hz (configurable)
    → diseño Kaiser con scipy.signal.kaiserord
    → aplicar con scipy.signal.filtfilt (fase lineal, delay neto = 0)
    → loguear: orden del filtro, delay, atenuación

  PASO 4 — Alineación temporal por GCC-PHAT
    → para cada ángulo de mesa:
        → tomar mic de referencia de ese ángulo como señal maestra
        → calcular delay de cada mic del array respecto a la referencia
           usando GCC-PHAT en Fourier (cross-correlación con blanqueo de fase)
        → alinear cada mic desplazando por su delay
        → loguear delay de cada mic en muestras y ms

  PASO 5 — Detección de onset y offset
    → usar mic de referencia de cada ángulo
    → estimar piso de ruido con primeros 3 segundos (mediana de RMS)
    → umbral = piso + MARGEN_DB (configurable, default 12 dB)
    → onset = primer frame sobre el umbral
    → offset = último frame sobre el umbral
    → aplicar roll-on de 500ms antes del onset (configurable)
    → aplicar roll-off de 500ms después del offset (configurable)
    → loguear onset, offset y duración útil de cada ángulo

  PASO 6 — Igualación de duración
    → duración común = mínimo de todas las duraciones útiles
    → recortar todos los archivos al mínimo común
    → loguear duración común final

  PASO 7 — Cálculo de STFT
    → frame size = 10ms (configurable, potencia de 2)
    → ventana Hann, 75% overlap
    → calcular para todos los mics de todos los ángulos
    → loguear progreso: ángulo X/19, mic Y/19

  PASO 8 — Cálculo de SPL por banda de 1/3 de octava
    → bandas de 1/3 oct según IEC 61260 (100 Hz a 10 kHz aprox)
    → para cada banda: sumar energía de los bins de frecuencia dentro
      de los límites inferior y superior de la banda
    → SPL = 10 * log10(energía + 1e-10)
    → resultado: tensor (n_mics, n_angulos, n_bandas, n_frames) float32
    → loguear: shape del tensor y tamaño en MB

  PASO 9 — Guardar sesión
    → guardar tensor como .npy en carpeta del proyecto
    → guardar metadatos como .json
    → permite cargar sesión anterior sin reprocesar
```

---

## 5. Tensor SPL

```python
# Shape: (n_mics, n_angulos, n_bandas, n_frames)
# Dtype: float32
# Ejemplo con configuración actual:
#   n_mics   = 19
#   n_angulos= 19
#   n_bandas = 30  (bandas de 1/3 oct de ~100Hz a ~10kHz)
#   n_frames = duración_común / hop_size
# Tamaño estimado: ~65 MB

tensor_spl[mic_idx, ang_idx, banda_idx, frame_idx] = SPL_en_dB
```

### Acceso en tiempo real (todo en RAM, sin loops Python)

```python
# Ventana de W frames centrada en frame t para banda b:
segmento = tensor_spl[:, :, b, t-W//2 : t+W//2]       # (19, 19, W)
energia  = np.mean(10**(segmento/10), axis=2)           # (19, 19)
spl_inst = 10 * np.log10(energia + 1e-10)               # (19, 19)

# Balloon para ese instante → matriz lista para graficar
balloon  = spl_inst   # shape (19, 19)
```

---

## 6. Visualización

### Polar 2D (matplotlib embebido en PyQt6)
- Eje angular: ángulo del array (0° a 180°, espejado a 360°)
- Radio: SPL normalizado al máximo del frame
- Animado frame a frame sincronizado con slider de tiempo
- Punto naranja en el ángulo de máxima energía

### Balloon 3D (pyqtgraph OpenGL embebido en PyQt6)
- Conversión de coordenadas esféricas a cartesianas:
  ```
  x = r * sin(θ) * cos(φ)
  y = r * sin(θ) * sin(φ)
  z = r * cos(θ)
  ```
  donde θ = ángulo array, φ = ángulo mesa, r = SPL normalizado
- Interpolación spline 19×19 → 72×72 puntos para superficie suave
- Suavizado gaussiano opcional (checkbox)
- Rotación con mouse
- Animado sincronizado con polar 2D

### Sincronización
- Slider de tiempo controla ambos gráficos simultáneamente
- Audio del mic de referencia (mic_ref_ang_{DIN}_90.wav) reproducido
  sincronizado con el slider

---

## 7. Controles de la GUI

### Pantalla de carga
| Control | Tipo | Descripción |
|---|---|---|
| Carpeta forte | Campo + botón | Ruta a carpeta con WAVs forte |
| Carpeta piano | Campo + botón | Ruta a carpeta con WAVs piano |
| Plantilla mics | Campo texto | ej: mic_{MIC}_ang_{DIN}_{ANG}.wav |
| Plantilla refs | Campo texto | ej: mic_ref_ang_{DIN}_{ANG}.wav |
| N° micrófonos | SpinBox | 1 a 64 |
| Ángulo inicio array | SpinBox | grados |
| Ángulo fin array | SpinBox | grados |
| Paso mesa | SpinBox | grados |
| Roll-on | SpinBox | ms, default 500 |
| Roll-off | SpinBox | ms, default 500 |
| Umbral onset | SpinBox | dB, default 12 |
| Frame STFT | ComboBox | 10/20/30/50 ms |
| Botón Procesar | QPushButton | arranca el pipeline |
| Botón Cargar sesión | QPushButton | carga .npy previo |
| Barra de progreso | QProgressBar | 0 a 100% |
| Panel de log | QTextEdit (readonly) | mensajes con timestamp |

### Pantalla de visualización
| Control | Tipo | Descripción |
|---|---|---|
| Selector dinámica | ComboBox | forte / piano |
| Slider frecuencia | QSlider | bandas de 1/3 oct disponibles |
| Label frecuencia | QLabel | muestra Hz de la banda actual |
| Slider tiempo | QSlider | 0 a duración común |
| Label tiempo | QLabel | muestra segundos |
| Slider ventana | QSlider | 30ms a 500ms |
| Label ventana | QLabel | muestra ms actual |
| Botón Play | QPushButton | inicia animación + audio |
| Botón Stop | QPushButton | detiene animación + audio |
| Checkbox suavizado | QCheckBox | activa gaussian_filter 2D |

---

## 8. Audio de referencia

- Archivo: `mic_ref_ang_{DIN}_90.wav` (ángulo de mesa 90°)
- Reproducción sincronizada con el slider de tiempo
- Al mover el slider manualmente: seek al instante correspondiente
- Al cambiar dinámica: cambiar al archivo de referencia de esa dinámica
- Implementación: QMediaPlayer de PyQt6 o sounddevice para mayor control

---

## 9. Persistencia de sesión

```
proyecto/
  tensor_forte.npy     → tensor SPL de forte (~65MB)
  tensor_piano.npy     → tensor SPL de piano (~65MB)
  sesion_forte.json    → metadatos (sr, angulos, bandas, duracion, etc.)
  sesion_piano.json    → metadatos
```

Al arrancar el programa, si existen estos archivos en la carpeta del
proyecto, el botón "Cargar sesión anterior" se habilita y salta
directamente al visualizador sin reprocesar.

---

## 10. Empaquetado

```bash
# Windows (.exe)
pyinstaller --onefile --windowed --name "DirectividadVocal" main.py

# Mac (.app)
pyinstaller --onefile --windowed --name "DirectividadVocal" main.py
```

Compilar en cada sistema operativo por separado.

---

## 11. Decisiones de diseño documentadas

| Decisión | Justificación |
|---|---|
| Dominio temporal para mic 9 | Evita problemas de ganancia de STFT |
| GCC-PHAT para alineación | Robusto con señales tonales (voz) |
| FIR con filtfilt | Fase lineal exacta, delay neto cero |
| Tensor precalculado en RAM | Animación fluida sin acceso a disco |
| Interpolación spline (no suavizado) | Datos reales entre puntos medidos |
| Suavizado gaussiano opcional | Estético, no altera datos medidos |
| Duración = mínimo entre ángulos | Sin relleno de zeros artificial |
| Ventana variable 30-500ms | Trade-off resolución temporal/frecuencial |
| Audio ref = ángulo 90° | Frente de la cantante, más representativo |
| OOP con PyQt6 | Estado complejo, GUI naturalmente orientada a objetos |
| numpy en vez de TensorFlow | Operaciones matriciales simples, sin GPU |
| .npy para persistencia | Carga en <1s, sin reprocesar |

---

## 12. Limitaciones metodológicas documentadas

1. **Segmentación por nota:** no se segmenta por nota individual. La
   ventana temporal puede contener mezcla de notas distintas. Se recomienda
   usar ventanas largas (≥300ms) para minimizar el efecto.

2. **Simetría para ángulos faltantes:** los ángulos 0°, 10° y 20° se
   reemplazan por simetría con 180°, 170° y 160°. Válido bajo la hipótesis
   de simetría izquierda-derecha de la voz cantada.

3. **Interpolación del mic 9:** el mic 9 (80°) es sintético, generado por
   promedio temporal entre mic 8 y mic 10 tras alineación por GCC-PHAT.

4. **Cobertura espectral:** la escala F4-F5 cubre principalmente 315-700 Hz
   en fundamentales. Las bandas fuera de este rango contienen solo armónicos
   y su interpretación debe hacerse con cautela.

5. **Variación de timing entre tomas:** la cantante puede haber cantado cada
   nota con duración levemente distinta en cada posición de mesa. La
   alineación por GCC-PHAT corrige el inicio pero no cuantiza las notas.