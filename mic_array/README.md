# mic_array — Módulo `MicArray`

Clase principal para representar, procesar y analizar una medición de directividad polar de la voz cantada.

## Estructura de datos

```
tensor : np.ndarray  shape (n_angles, n_elevations, n_samples)
```

- **Eje 0 — azimut:** ángulos en grados, típicamente `[0, 10, …, 180]`
- **Eje 1 — elevación:** etiquetas `['ref', 0, 10, …, 180]` — `'ref'` es el micrófono de referencia frontal
- **Eje 2 — tiempo:** muestras a `sr` Hz (por defecto 44 100 Hz)

Los valores del tensor están en FS (float32 normalizado) hasta llamar a `to_spl()`, que los convierte a Pascales.

---

## Atributos principales

| Atributo | Tipo | Descripción |
|---|---|---|
| `tensor` | ndarray float32 | Audio (n_az, n_el, n_smp) |
| `sr` | int | Sample rate en Hz |
| `angles` | list[int] | Azimuts en grados |
| `elevations` | list | Etiquetas de elevación (`'ref'` o entero) |
| `calibration` | ndarray o None | Factor K por elevación en dB |
| `_is_spl` | bool | True si el tensor está en Pascales |
| `leq_freqs` | ndarray o None | Frecuencias centrales (n_bands,) |
| `leq_levels` | ndarray o None | Leq por banda (n_az, n_el, n_bands) dB |
| `leq_global` | ndarray o None | Leq broadband (n_az, n_el) dB |
| `notes` | dict o None | `{nota: MicArray}` — tras extract_all_notes() |
| `scale` | dict o None | `{nombre: freq_hz}` de la escala |
| `downsampling_graph` | int | Factor de decimación para plots (default 10) |
| `smoothing_ms` | float | Ventana de suavizado de envolvente en ms (default 20) |

---

## Constructores

### `MicArray.from_audio(path, array_pattern, ref_pattern=None)`

Carga desde una carpeta plana de archivos WAV. Los patrones usan `{H}` para el azimut y `{MIC}` (número de mic, se convierte a elevación como `(n-1)*10`) o `{V}` (ángulo de elevación directo).

```python
ma = MicArray.from_audio(
    "data/media",
    array_pattern = "mic_{MIC}_ang_forte_{H}.wav",
    ref_pattern   = "mic_ref_ang_forte_{H}.wav",
)
```

Construye el tensor zero-padded al largo máximo de todos los archivos. Auto-detecta azimuths, elevaciones y sample rate.

### `MicArray.from_tensor(path, sr=44100)`

Carga desde `.npy` o `.npz`. Los archivos `.npz` guardados con `save()` restauran también `sr`, `angles`, `elevations` y `calibration`.

```python
ma = MicArray.from_tensor("data/tensores/forte_full_aligned.npz")
```

### `MicArray.from_export(path, pattern='mic_{H}_{V}.wav')`

Carga desde carpeta exportada por `export_wavs()`. `{H}` = azimut, `{V}` = elevación en grados.

---

## Procesamiento de señal

### `hpf(cutoff_hz)`

Filtro pasa-altos Butterworth de 4° orden aplicado a todas las posiciones del tensor in-place.

```python
ma.hpf(200)   # elimina frecuencias < 200 Hz
```

### `align_takes(elevation='ref', target_onset=1.0, threshold_dB=-40)`

Alinea todas las tomas de azimut a un tiempo de onset común. Detecta el onset en la elevación indicada por umbral de RMS en dBFS y desplaza **todas las elevaciones** de esa toma. Debe ejecutarse antes de `align_to_ref`.

```python
ma.align_takes(elevation='ref', target_onset=0.5, threshold_dB=-55)
```

### `align_to_ref(elevation='ref')`

Alinea cada elevación respecto a la referencia usando GCC-PHAT. Para cada toma de azimut calcula el TDOA promedio entre la referencia y el resto de elevaciones y desplaza en número entero de muestras.

```python
ma.align_to_ref(elevation='ref')
```

### `normalize_takes(elevation='ref', ref_azimuth=0)`

Normaliza el nivel RMS de todas las tomas relativo a la toma de referencia `ref_azimuth`. Útil si hubo variación de intensidad vocal entre tomas.

### `copy()`

Devuelve un nuevo `MicArray` con copia independiente del tensor.

---

## Calibración y unidades SPL

### `calibrate(path, array_pattern, ref_pattern=None, spl_cal=94)`

Carga archivos WAV de calibración (tono de 1 kHz a `spl_cal` dB SPL) y calcula el factor `K` por elevación:

```
K[i_el] = spl_cal - 20·log10(RMS_cal)
```

Resultado en `self.calibration` (ndarray de shape `(n_elevations,)`).

### `to_spl()`

Convierte el tensor in-place a Pascales usando `self.calibration`. Requiere haber llamado `calibrate()` primero. Tras esta llamada, el RMS de cualquier señal da dB SPL via `20·log10(RMS / 20µPa)`.

`save()` deshace la conversión automáticamente antes de escribir para no perder precisión.

---

## Detección y extracción de notas

### `detect_notes(scale=None, elevation='ref', hop_length=512, tolerance_cents=50, min_purity=0.8, confidence=None, start_s=0.0)`

Detecta el intervalo (inicio/fin en muestras) de cada nota de la escala en cada toma, usando **pYIN** (librosa) sobre la elevación indicada. Cada frame de F0 se asigna a la nota más cercana (en cents); los segmentos con pureza menor a `min_purity` se rechazan.

Parámetros clave:
- `start_s` — descarta los primeros N segundos (ruido antes del ataque)
- `confidence` — alias de `min_purity`; si se pasa, lo sobreescribe

Retorna `segments`: lista de dicts, uno por azimut:
```python
segments[i_az][note_name] = {'start': int, 'end': int, 'purity': float}
# start/end son índices de muestra absolutos en el tensor original
```

Imprime y muestra un DataFrame estilizado con duraciones y purezas por toma.

### `extract_note(segmentos, note)`

Retorna un nuevo `MicArray` recortado al intervalo de `note`. Las tomas sin detección quedan en cero.

### `extract_all_notes(segmentos, scale=None)`

Llama a `extract_note` para todas las notas de la escala y guarda los resultados en `self.notes`.

```python
ma.extract_all_notes(segments)
ma.notes['Fa4']   # → MicArray con shape (19, 20, ~27 000)
```

---

## Cálculo de Leq

### `compute_leq(bands='1/3', p_ref=20e-6, method='iir')`

Calcula el nivel equivalente en bandas de octava para cada posición del tensor completo. Usa `FilterBank` internamente.

- `method='iir'` — filtros Butterworth IEC 61260, preciso (lento)
- `method='fft'` — bandas rectangulares, rápido (exploración)

Resultados en `self.leq_freqs`, `self.leq_levels`, `self.leq_global`.

### `compute_leq_notes(bands='1/3', p_ref=20e-6, method='fft')`

Ejecuta `compute_leq` sobre cada `MicArray` en `self.notes`. Requiere `extract_all_notes()` previo.

---

## Visualización

### `plot(azimuth=None, elevation=None, envelope=True, dB=False, floor_dB=-80, yrange=None, title=None)`

Señal en el tiempo. Tres modos según qué parámetros se pasen:
- `azimuth + elevation` → señal única
- `azimuth` only → todas las elevaciones de esa toma
- `elevation` only → todas las tomas para esa elevación

`envelope=True` muestra la envolvente suavizada (Hilbert + media móvil de `smoothing_ms` ms).

### `plot_leq(azimuth=None, elevation=None, frange=None, vrange=None, colorscale='Viridis')`

Espectro en bandas. Tres modos:
- `azimuth + elevation` → gráfico de barras (espectro individual)
- `azimuth` only → heatmap elevaciones × bandas
- `elevation` only → heatmap azimuts × bandas

### `plot_leq_global(elevation='ref', yrange=None)`

Barras con el Leq broadband por azimut para una elevación dada. Incluye línea de media energética.

### `report_leq_global(elevation='ref')`

Tabla pandas con Leq broadband por azimut + media energética.

### `plot_f0(azimuth, scale=None, elevation='ref', hop_length=512, band_cents=50, segments=None)`

Tracking de F0 (pYIN) en cents para una toma. Muestra bandas de aceptación ±50 ¢ por nota. Si se pasa `segments`, dibuja líneas verticales negras punteadas en el inicio y fin de cada nota detectada.

### `plot_tune(azimuth, scale=None, elevation='ref', confidence_threshold=0.5)`

Desviación media de afinación en cents por nota para una toma. Verde ≤ 25 ¢, amarillo ≤ 50 ¢, rojo > 50 ¢.

### `plot_leq_by_note(elevation='ref', yrange=None)`

Media ± std del Leq global por nota (barras con error). En `elevation='ref'` refleja consistencia vocal entre tomas; en otro ángulo refleja directividad.

### `report_leq_by_note(elevation='ref')`

Tabla con media, std, mín y máx del Leq por nota.

### `plot_rms_takes(elevation='ref', floor_dB=-60)`

VU-meter de RMS por toma (barras). Útil para detectar tomas con nivel anómalo.

### `plot_note_quality(segments)` / `listen_bad_detections(segments, elevation='ref')`

Heatmap de pureza de detección (verde / amarillo / rojo / gris). El segundo método permite escuchar las tomas problemáticas.

---

## Persistencia

### `save(path)`

Guarda tensor, sr, angles, elevations y (si existe) calibration en `.npz`. Deshace `to_spl()` antes de escribir.

### `export_wavs(path, nota='')`

Exporta cada posición (azimut × elevación) como WAV individual. Nomenclatura: `mic_{az}_{el}_{nota}.wav`. Omite la elevación `'ref'`.

---

## Convenciones de indexación

```python
i_az = ma._az_to_row(90)    # índice del azimut 90°
i_el = ma._el_to_col('ref') # índice de la elevación ref
señal = ma.tensor[i_az, i_el, :]
```

Ambos métodos lanzan `ValueError` si el valor no existe en `self.angles` / `self.elevations`.
