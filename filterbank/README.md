# filterbank — Módulo `FilterBank`

Banco de filtros de octava fraccionaria con cumplimiento IEC 61260-1.  
Soporta resoluciones 1/1, 1/3, 1/6, 1/12 y 1/24 de octava en el rango 20 Hz – 20 kHz.

## Uso básico

```python
from filterbank import FilterBank

fb = FilterBank(sr=44100, bands='1/3')

# Leq por banda — IEC 61260 compliant (usa sosfiltfilt con Butterworth)
freqs, levels = fb.leq(signal, method='iir')

# Leq por banda — rápido (bandas rectangulares via FFT)
freqs, levels = fb.leq(signal, method='fft')

# Leq broadband (suma energética sobre todas las bandas)
leq_total = fb.leq_global(signal)

# Etiquetas para informes
print(fb.center_freqs_nominal)   # [20, 25, 31.5, ..., 20000]
print(fb.center_freqs_exact)     # valores exactos usados en los filtros
```

## Parámetros del constructor

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `sr` | int | 44100 | Sample rate en Hz |
| `bands` | str | `'1/3'` | Resolución: `'1/1'`/`'octave'`, `'1/3'`, `'1/6'`, `'1/12'`, `'1/24'` |
| `fmin` | float | 20 | Frecuencia central mínima en Hz |
| `fmax` | float | 20000 | Frecuencia central máxima en Hz |
| `order` | int o None | Auto | Orden del filtro Butterworth. Si es None, se usa el orden por defecto según resolución. |

Órdenes por defecto:

| Resolución | Orden |
|---|---|
| 1/1 | 4 |
| 1/3 | 6 |
| 1/6 | 8 |
| 1/12 | 12 |
| 1/24 | 16 |

## Frecuencias centrales

Las bandas 1/1 y 1/3 usan las frecuencias nominales IEC 61260-1. Las resoluciones más finas (1/6 a 1/24) se generan con la fórmula exacta:

```
f_c(n) = 1000 · 2^(n/N)
```

donde `N` es el denominador de la resolución. Si `f_c` cae dentro del 2% de un nominal IEC conocido, se usa el nominal; en caso contrario se redondea a 3 cifras significativas.

Para 1/3 de octava entre 20 Hz y 20 kHz resultan **31 bandas**.

Los bordes de cada banda son:
```
f_lo = f_c / 2^(1/(2N))
f_hi = f_c × 2^(1/(2N))
```

## Decimación por grupos

Para garantizar estabilidad numérica en bandas de baja frecuencia, las señales se deciman antes de aplicar el filtro, reduciendo la frecuencia de Nyquist de trabajo:

| Grupo | Bandas (nominal) | Decimación | sr_work |
|---|---|---|---|
| A | 20 – 250 Hz | ÷5 → ÷10 | 882 Hz |
| B | 315 – 2500 Hz | ÷5 | 8820 Hz |
| C | 3150 – 20000 Hz | ninguna | 44100 Hz |

Esto es válido para sr = 44 100 Hz y 48 000 Hz. La decimación usa `scipy.signal.decimate` con `zero_phase=True` en cada etapa.

## Métodos públicos

### `leq(signal, p_ref=20e-6, method='iir')`

Calcula el Leq por banda para una señal 1D.

**Parámetros:**
- `signal` — señal de audio 1D (numpy array)
  - En Pascales (tras `MicArray.to_spl()`) → resultado en dB SPL
  - En FS normalizado → usar `p_ref=1.0` para dBFS
- `p_ref` — presión de referencia (default 20 µPa)
- `method` — `'iir'` (IEC 61260, preciso) o `'fft'` (bandas rectangulares, rápido)

**Retorna:** `(freqs, levels)` — arrays de shape `(n_bands,)`.

El método `'iir'` aplica `sosfiltfilt` (Butterworth zero-phase) sobre la señal decimada. El método `'fft'` suma la potencia espectral dentro de los bordes de cada banda.

### `leq_global(signal, p_ref=20e-6, method='iir')`

Leq broadband por suma energética sobre todas las bandas:

```
Leq_global = 10·log10(Σ 10^(Leq_i/10))
```

## Integración con MicArray

`MicArray.compute_leq()` instancia `FilterBank` internamente y lo aplica a cada posición del tensor. Para uso directo con mayor control (resoluciones 1/6–1/24, fmin/fmax personalizado):

```python
from filterbank import FilterBank

fb = FilterBank(sr=44100, bands='1/6', fmin=200, fmax=8000)
freqs, levels = fb.leq(signal, method='iir')
```

## Representación

```python
repr(fb)
# FilterBank(bands='1/3', sr=44100, order=6, n_bands=31, fmin=20, fmax=20000)
```

Al construir, se imprime un resumen de los grupos de decimación con sus rangos de frecuencia y sr_work, útil para verificar la configuración.
