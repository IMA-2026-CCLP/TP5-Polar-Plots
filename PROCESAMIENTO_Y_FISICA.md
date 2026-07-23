# Procesamiento de señales y física del experimento

Documento de referencia con la lógica matemática/física detrás del pipeline (`mic_array/patron.py`, `filterbank/filterbank.py`, y el post-procesado que hace el GUI en `app/plot/balloon.py`). Complementa a `PIPELINE.md` (que explica el *uso* del pipeline paso a paso) con el *por qué* y las fórmulas exactas.

## 1. Geometría del experimento

- Array semicircular de 19 micrófonos en elevación (θ), de 0° a 180° en pasos de 10°, a 2,5 m de la boca del cantante, más 1 micrófono de referencia (`theta='ref'`) en posición frontal fija.
- Plataforma giratoria rota al cantante en azimut (φ), 0°–180° en pasos de 10° → 19 tomas.
- Tensor resultante: `(n_azimut, n_elevación, n_muestras) = (19, 20, ~286000)` a 44100 Hz. Cada "toma" de azimut es una grabación separada — no hay sincronismo temporal entre tomas, de ahí la necesidad de alinearlas (sección 2).

## 2. Preprocesamiento temporal

### 2.1 Filtro pasa-altos

Butterworth de 4º orden, corte configurable (default 200 Hz), aplicado sobre una copia del tensor. Elimina DC y ruido de muy baja frecuencia (rumble de la plataforma giratoria, HVAC).

### 2.2 Alineación de tomas — `align_takes()`

Cada toma de azimut arranca en un instante distinto (se grabaron por separado). Se detecta el *onset* de la señal en una elevación de referencia (`_detect_onset`):

- Ventana deslizante de `window_ms` (default 50 ms) con 50% de solape.
- Se usa la **mediana** de `|señal|` dentro de cada ventana (no RMS/media) — más robusta a clicks/impulsos aislados que un RMS.
- El onset es el índice de la primera ventana cuya mediana supera `threshold_dB` (default −40 dBFS, convertido a amplitud lineal `10^(threshold_dB/20)`).

Con el onset detectado, se desplaza **toda la toma** (todas las elevaciones juntas) en bloque para que el onset caiga en `target_onset` segundos — preserva la relación temporal relativa entre elevaciones de una misma toma, solo corrige el offset entre tomas distintas.

### 2.3 Alineación entre elevaciones — `align_to_ref()` (GCC-PHAT)

Una vez que todas las tomas comparten origen temporal, se corrige el retardo de propagación acústica entre el micrófono de referencia y cada elevación (por la diferencia de distancia/trayecto), usando **GCC-PHAT** (Generalized Cross-Correlation with PHAse Transform):

```
G(f)      = S₁(f) · conj(S₂(f))                    (cross-spectrum)
G_phat(f) = G(f) / (|G(f)| + ε)                     (blanqueo de fase — PHAT)
gcc(τ)    = IFFT(G_phat)
τ̂         = argmax |gcc(τ)|                          (TDOA estimado, en muestras)
```

PHAT pondera todas las frecuencias por igual (ignora la magnitud del espectro cruzado), lo que da picos de correlación más agudos que una correlación cruzada cruda — mejor resolución de TDOA en señales de banda ancha como la voz.

- Se calcula un TDOA por cada elevación no-referencia, se **promedian** todos los TDOA de una toma, y se aplica un único desplazamiento entero (en muestras) a toda la toma — no un desplazamiento independiente por elevación, para no introducir inconsistencias artificiales entre elevaciones cercanas.
- `energy_threshold_dB` (opcional): enmascara a cero los tramos de la señal de referencia por debajo de ese nivel (en bloques de 512 muestras) antes de correlacionar, para que el ruido de fondo/silencio no contamine la estimación de TDOA.

## 3. Calibración y conversión a SPL

- Se graba un tono de 1 kHz a `spl_cal` dB SPL conocido (default 94, pistófono) para cada elevación.
- Factor de calibración: **K = spl_cal − 20·log₁₀(RMS_cal)**, uno por elevación (`self.calibration`).
- `to_spl()` reescala el tensor completo por `K` de forma que `RMS(señal) / 20 µPa` dé directamente dB SPL al aplicar `20·log10(·)`. `save()` deshace esta conversión antes de escribir a disco (se guarda siempre en unidades de fondo de escala, no en Pascales) para no perder precisión al recargar.
- K típicos del experimento: ref ≈ 102.85 dB, 0° ≈ 100.87 dB, 90° ≈ 100.20 dB, 180° ≈ 101.25 dB.

## 4. Banco de filtros de fracción de octava (`filterbank/filterbank.py`)

Implementa análisis en bandas de 1/1 a 1/24 de octava, con frecuencias centrales nominales IEC 61260-1 para 1/1 y 1/3 (y generadas por fórmula base-2 para 1/6, 1/12, 1/24).

- **Ancho de banda**: para N-ava de octava, el borde de banda es `f_c · 2^(±1/2N)`.
- **Decimación escalonada**: antes de filtrar cada grupo de bandas bajas, la señal se decima (`scipy.signal.decimate`, `zero_phase=True`) para que el filtro Butterworth trabaje con más resolución relativa cerca de Nyquist — necesario para estabilidad numérica de bandas de 20 Hz–20 kHz en un solo pase. Cada grupo de frecuencias usa su propio `sr` de trabajo tras decimar.
- **Dos métodos de Leq**:
  - `method='iir'` (compliant IEC 61260): filtra con Butterworth pasa-banda (`sosfiltfilt`, fase cero) sobre la señal decimada de cada grupo, y calcula RMS de la señal filtrada. Más lento (~2 min para el tensor completo) pero es el que se usa para resultados finales.
  - `method='fft'`: hace una FFT de la señal completa y suma la potencia espectral (`|X|²`, con corrección de Parseval `×2` para todo bin salvo DC/Nyquist) dentro del rango `[f_c/2^(1/2N), f_c·2^(1/2N)]` de cada banda — bandas rectangulares, no compliant IEC pero mucho más rápido, usado para exploración y en el pipeline de directividad del GUI.
- **Nivel**: `Leq = 20·log10(RMS / P_REF)`, con `P_REF = 20 µPa`.

## 5. Cómputo de directividad (`compute_directivity()`)

Proceso de 3 pasos, la parte central de todo el análisis:

**Paso 1 — SPL por banda, para cada posición (azimut × elevación):**
```
SPL[az, θ, f] = Leq de la banda f en esa posición
```

**Paso 2 — corrección de emisión por toma** (compensa que el cantante no emite exactamente igual en cada toma de azimut, ya que son grabaciones separadas):
```
delta[az, f]      = SPL[ref_azimuth, ref_theta, f] − SPL[az, ref_theta, f]
SPL_corr[az,θ,f]  = SPL[az, θ, f] + delta[az, f]
```
Se usa siempre el micrófono de referencia (`ref_theta`, típicamente `'ref'`) como testigo de emisión: la diferencia entre lo que el mic de referencia capturó en la toma de azimut de referencia (`ref_azimuth`, típicamente 0°) contra lo que capturó en la toma actual, se suma a **todas** las elevaciones de esa toma por igual. Esto lleva todas las tomas al mismo "nivel de emisión" antes de comparar direcciones.

**Paso 3 — normalización a la posición de referencia (0 dB on-axis):**
```
dir[az, θ, f] = SPL_corr[az, θ, f] − SPL_corr[ref_azimuth, ref_theta_plot, f]
```
Hace que `(ref_azimuth, ref_theta_plot)` (por default 0°/0°) sea 0 dB en cada banda — el resto de las direcciones queda expresado en dB relativos a esa referencia, que es lo que finalmente se grafica en los patrones polares/3D.

No hace falta correr `level_compensation()` ni `normalize()` (métodos más viejos/manuales) antes de esto — `compute_directivity()` hace su propia corrección y normalización de punta a punta.

`compute_directivity_notes()` corre este mismo proceso independientemente sobre cada `MicArray` en `self.notes`.

## 6. Detección de notas (`detect_notes()`)

- **pYIN** (librosa) trackea F0 frame a frame sobre la elevación elegida (default `'ref'`), con `fmin`/`fmax` derivados de la escala ±10%.
- Cada frame se asigna a la nota de la escala más cercana en **cents**: `cents = 1200·log2(f_frame / f_nota)`; se acepta si `|cents| ≤ tolerance_cents` (default 50 ¢ = medio semitono).
- **Detección de transición por gradiente**: se interpola linealmente la curva de cents sobre los frames no sonoros (para no generar picos falsos de gradiente en los bordes sonoro/no-sonoro), y se calcula `|gradiente|` en cents/frame. Frames con gradiente > `gradient_thresh` (default 25 ¢/frame) se consideran "en transición" (portamento/glissando) y se excluyen al determinar los bordes del segmento — así el segmento aceptado corresponde a la parte "asentada" de la nota, no a la subida/bajada de tono.
- **Pureza**: fracción de frames del segmento estable correctamente asignados a la nota. Segmentos con pureza `< min_purity` (default 0.8) se rechazan — esa toma queda en cero para esa nota en `extract_all_notes()`, en vez de usarse contaminada.

## 7. Simetrías (`core/symmetry_utils.apply_symmetry`, usado por el GUI)

Expande los datos medidos duplicando ángulos simétricos, para mostrar un patrón "completo" cuando solo se midió medio plano:

- **`azimuth`**: refleja `az → (360 − az) mod 360`, descartando los extremos duplicados (0°/180°, que son su propio espejo) al concatenar.
- **`elevation`**: refleja `θ → −θ`, y **solo rellena huecos** (`np.where(nan_mask, sym_data, ...)`) — si una elevación ya tiene dato medido, no se pisa con el simétrico; el simétrico solo tapa lo que falta.
- **`both`**: aplica ambas.

Esto es puramente para visualización — no altera los datos ya medidos, solo completa direcciones no medidas asumiendo simetría del patrón.

## 8. Post-procesado específico del GUI (`app/plot/balloon.py`)

Estas etapas son posteriores a `compute_directivity()` y solo afectan cómo se **dibuja** el patrón, no los datos calculados:

### 8.1 Suavizado circular (Polar 2D, y por anillo de azimuth en 3D/Esfera)

`_smooth_circular(y, window, method)` — el anillo de azimut es una señal periódica (0°=360°), así que el suavizado debe ser circular (el final se continúa con el principio):

- **`gaussian`** (default): `scipy.ndimage.gaussian_filter1d(y, sigma=window/3, mode='wrap')`. Pondera más los puntos cercanos, sin corte abrupto — no introduce "ripple" (ondulación falsa).
- **`savgol`**: Savitzky-Golay (`scipy.signal.savgol_filter`) con padding circular manual antes de filtrar y recorte después — ajusta un polinomio local, preserva mejor picos/nulos angostos que gaussian o moving average.
- **`moving_average`**: promedio móvil rectangular simple con padding circular — el más agresivo, puede introducir ondulaciones artificiales si la ventana es grande.
- La ventana está en **cantidad de puntos medidos** (no en grados) — con una resolución de 10° hay ~19-36 puntos por vuelta completa, así que ventanas grandes (>10) empiezan a distorsionar lóbulos/nulos reales, no solo a atenuar ruido.

### 8.2 Interpolación angular (Polar 2D)

Tras suavizar (si corresponde), `scipy.interpolate.interp1d` con `kind='cubic'/'quadratic'/'linear'` rellena puntos intermedios entre las mediciones cada `interp_deg` grados — puramente visual, no inventa ni descarta información real, solo dibuja una curva continua en vez de un polígono.

### 8.3 Grilla esférica (3D / Esfera)

`_build_hemisphere_grid()` arma la superficie 3D combinando pares frente/atrás de elevación (`_build_full_ring`, promedio energético en las costuras donde ambos existen) y ajustando un **spline bivariado** (`scipy.interpolate.RectBivariateSpline`, orden cúbico en azimut, orden ≤3 en elevación) sobre la grilla `(elevación, azimut)` medida:

- El factor de suavizado `s` del spline (0 = pasa exacto por los datos medidos; mayor = se aparta para suavizar ruido) es independiente del suavizado circular de 8.1 — actúa sobre la superficie completa, no solo por anillo.
- El cénit (θ=90°) se trata aparte: se calcula un promedio energético de todos los azimuts en esa elevación (en el cénit, todos los azimuts miden literalmente el mismo punto físico) y se agrega como restricción de fila constante al spline antes de interpolar, para que la superficie converja suavemente ahí en vez de generar "rayos" radiales artificiales en el casquete superior.
