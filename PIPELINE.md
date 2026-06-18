# Pipeline — Directividad Polar de la Voz Cantada

## Contexto experimental

Se mide la directividad polar de la voz cantada en una cámara anecoica.
Un array de 19 micrófonos está dispuesto en una semicircunferencia vertical alrededor del cantante (a 2,5 m de la boca), separados 10° entre sí (0°–180° de elevación). Un micrófono de referencia captura la toma en la posición frontal. Una plataforma giratoria rota al cantante en pasos de 10° en azimut (0°–180°), resultando en **19 tomas de azimut × 20 elevaciones** (19 de array + 1 referencia).

El resultado es un tensor tridimensional:
```
tensor.shape = (n_azimuts, n_elevaciones, n_muestras)
              = (19, 20, ~286 000)   ← a 44 100 Hz
```

Los ejes son:
- **Eje 0 (azimut):** 0°, 10°, 20°, …, 180°
- **Eje 1 (elevación):** `'ref'`, 0°, 10°, …, 180°
- **Eje 2 (tiempo):** muestras a 44 100 Hz

---

## Parte 1 — Preprocesamiento (`polar_preprocesamiento.ipynb`)

### 1. Carga de archivos

Los archivos WAV están organizados en carpetas planas con nombres que siguen un patrón. El patrón usa los tokens `{MIC}` o `{V}` para la elevación y `{H}` para el azimut.

```python
ma = MicArray.from_audio(
    "data/media",
    array_pattern = "mic_{MIC}_ang_forte_{H}.wav",
    ref_pattern   = "mic_ref_ang_forte_{H}.wav",
)
```

Internamente construye el tensor zero-padded al largo máximo de todos los archivos.

### 2. Filtrado de bajas frecuencias

Se aplica un filtro pasa-altos Butterworth de 4° orden para eliminar ruido DC y muy baja frecuencia (rumble de ventilación, plataforma giratoria). Se trabaja sobre una copia para preservar los datos crudos.

```python
ma_filtered = ma.copy()
ma_filtered.hpf(200)   # HPF 200 Hz, 4° orden Butterworth
```

### 3. Alineamiento de tomas (`align_takes`)

Cada toma de azimut fue grabada por separado, por lo que el inicio del sonido no es coincidente. Se detecta el onset de la señal de referencia (`elevation='ref'`) por umbral de RMS en dBFS y se desplazan **todas las elevaciones** de esa toma para que el onset quede en `target_onset` segundos.

```python
ma_aligned = ma_filtered.copy()
ma_aligned.align_takes(elevation='ref', target_onset=0.5, threshold_dB=-55)
```

El umbral de −55 dBFS se eligió observando el nivel de ruido de fondo en el gráfico de envolvente en dB de la referencia.

### 4. Alineamiento relativo a la referencia (`align_to_ref`)

Una vez que todas las tomas comparten el mismo origen temporal, se alinea cada elevación respecto al micrófono de referencia usando **GCC-PHAT**. Esto compensa el retardo de propagación por la diferencia de distancia entre micrófonos.

```python
ma_aligned_to_ref = ma_aligned.copy()
ma_aligned_to_ref.align_to_ref(elevation='ref')
```

El TDOA se calcula para cada elevación, se promedia y se aplica un desplazamiento entero de muestras.

### 5. Guardado del tensor

El tensor alineado se guarda en formato `.npz` para no repetir el preprocesamiento.

```python
ma_aligned_to_ref.save('data/tensores/forte_full_aligned.npz')
```

El archivo `.npz` almacena `tensor`, `sr`, `azimuth`, `elevation` y (si existe) `calibration`. Al recargar con `MicArray.from_tensor()` se restaura toda la metadata.

---

## Parte 2 — Estadísticas (`polar_estadisticas.ipynb`)

### 1. Carga del tensor preprocesado

```python
ma = MicArray.from_tensor('data/tensores/forte_full_aligned.npz')
```

### 2. Calibración

Los micrófonos se calibraron con un pistófono de 94 dB SPL a 1 kHz. Cada archivo de calibración se procesa para obtener un factor `K` (en dB) por elevación:

```
K = 94 - 20·log10(RMS_cal)
```

```python
ma.calibrate(
    path="data/media",
    array_pattern="mic_{MIC}_ang_cal.wav",
    ref_pattern="mic_ref_ang_cal.wav"
)
ma.to_spl()   # convierte el tensor a Pascales
```

Factores K típicos del experimento:

| Elevación | K (dB) |
|-----------|--------|
| ref       | 102.85 |
| 0°        | 100.87 |
| 90°       | 100.20 |
| 180°      | 101.25 |

Tras `to_spl()`, `RMS(señal) / 20µPa` da directamente dB SPL. El método `save()` deshace la conversión antes de escribir para no comprometer la precisión al recargar.

### 3. Cálculo de Leq por banda (`compute_leq`)

Se calcula el nivel equivalente en bandas de 1/3 de octava (IEC 61260-1) para cada posición del tensor. Los resultados quedan en:

- `ma.leq_freqs`  → frecuencias nominales (31 bandas, 20 Hz–20 kHz)
- `ma.leq_levels` → shape `(19, 20, 31)` — azimuts × elevaciones × bandas — en dB SPL
- `ma.leq_global` → shape `(19, 20)` — Leq broadband por posición

```python
# Rápido, para exploración
ma.compute_leq(bands='1/3', method='fft')

# IEC 61260 compliant, para resultados finales (~2 min)
ma.compute_leq(bands='1/3', method='iir')
```

Leq global típico para la elevación de referencia: **~89 dB SPL** (variación < 3 dB entre tomas).

### 4. Definición de la escala e instrumento

La escala grabada cubre una octava del registro medio-agudo de la voz:

```python
ma.scale = {
    'Fa4': 349.23, 'Sol4': 392.0,  'La4': 440.0,  'Sib4': 466.16,
    'Do5': 523.25, 'Re5':  587.33, 'Mi5': 659.25, 'Fa5':  698.46,
}
```

### 5. Detección automática de notas (`detect_notes`)

Se usa el algoritmo **pYIN** (librosa) para estimar la F0 frame a frame sobre la elevación de referencia. Cada frame se asigna a la nota más cercana en cents (tolerancia ±50 ¢). Los segmentos continuos con alta "pureza" (fracción de frames correctamente asignados) se aceptan; los contaminados se rechazan y esa toma queda en cero.

```python
segments = ma.detect_notes(start_s=0.3, confidence=0.4)
```

- `start_s=0.3` — descarta los primeros 300 ms de cada toma (ruido antes del ataque).
- `confidence=0.4` — umbral de pureza mínima para aceptar un segmento (alias de `min_purity`).

La función devuelve `segments`: una lista de dicts, uno por toma de azimut:
```
segments[i_az][note_name] = {'start': int, 'end': int, 'purity': float}
```
donde `start`/`end` son índices de muestra absolutos en el tensor original.

Para verificar visualmente la detección:
```python
ma.plot_f0(azimuth=40, segments=segments)
```

### 6. Extracción de notas

```python
ma.extract_all_notes(segments)
# → self.notes = {'Fa4': MicArray, 'Sol4': MicArray, ..., 'Fa5': MicArray}
```

Cada `ma.notes[nota]` es un `MicArray` independiente recortado al intervalo detectado. Las tomas no detectadas quedan en cero. Duraciones típicas: 600–1200 ms.

### 7. Leq por nota

```python
ma.compute_leq_notes()
```

Corre `compute_leq` sobre cada `MicArray` en `self.notes`. Permite comparar el espectro de cada nota por separado.

### 8. Análisis y visualizaciones

| Método | Qué muestra |
|---|---|
| `ma.plot_leq(elevation='ref')` | Heatmap azimuts × bandas para la referencia |
| `ma.plot_leq_global(elevation='ref')` | Leq broadband por azimut (barras) |
| `ma.report_leq_global(elevation='ref')` | Tabla numérica con media energética |
| `ma.plot_f0(azimuth=N, segments=segments)` | Tracking de F0 con intervalos detectados marcados |
| `ma.plot_tune(azimuth=N)` | Desviación media en cents por nota (afinación) |
| `ma.plot_leq_by_note(elevation='ref')` | Media ± std del Leq global por nota |
| `ma.report_leq_by_note(elevation='ref')` | Tabla con media, std, mín, máx por nota |
| `ma.plot_note_quality(segments)` | Heatmap de pureza de detección (verde/amarillo/rojo) |
| `ma.notes['Fa4'].listen(azimuth=130, elevation='ref')` | Reproducir una nota específica |

---

## Flujo completo resumido

```
WAVs crudos
  └─ from_audio()            carga y construye tensor (n_az, n_el, n_smp)
       └─ hpf(200)           elimina DC y baja frecuencia
            └─ align_takes() onset detection → todos los azimuts al mismo t₀
                 └─ align_to_ref() GCC-PHAT → alinea elevaciones entre sí
                      └─ save()   → forte_full_aligned.npz

forte_full_aligned.npz
  └─ from_tensor()
       └─ calibrate() + to_spl()    → tensor en Pascales
            └─ compute_leq('1/3')   → leq_levels (19, 20, 31)
                 └─ detect_notes()  → segments (pyin + pureza)
                      └─ extract_all_notes()  → self.notes
                           └─ compute_leq_notes()
                                └─ plot / report
```
