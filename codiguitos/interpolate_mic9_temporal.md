# interpolar_mic9_temporal.py

Genera los WAVs del **micrófono 9** (canal faltante del array semicircular)
interpolando en el **dominio temporal** entre el micrófono 8 (70°) y el
micrófono 10 (90°).

---

## Contexto

El array semicircular de 19 micrófonos cubre de 0° a 180° con un espaciado
de 10° entre micrófonos. El micrófono 9, ubicado en 80°, no grabó señal
válida. Este script genera una señal sintética para ese canal a partir de
sus dos vecinos inmediatos.

---

## Método

### Paso 1 — Alineación temporal por GCC-PHAT

Antes de promediar, las dos señales deben estar alineadas en el tiempo.
Aunque ambos micrófonos grabaron simultáneamente, pueden existir pequeñas
diferencias de delay por:

- Diferencias en la longitud del cable
- Latencia de los preamplificadores
- Diferencias de fase acústica por la posición en el array

Para calcular el delay se usa **GCC-PHAT** (Generalized Cross-Correlation
with Phase Transform), que opera en el dominio de Fourier:

```
1. FFT de mic 8  →  A
   FFT de mic 10 →  B

2. Cross-spectrum:  R = A · conj(B)

3. Blanqueo PHAT:   R = R / |R|    ← solo queda la información de fase

4. IFFT(R) → función de correlación de fase

5. Buscar el pico dentro de ±50 ms → delay en muestras
```

El blanqueo PHAT hace que todas las frecuencias contribuyan por igual
al resultado, evitando que los armónicos fuertes de la voz dominen
la estimación del delay.

### Paso 2 — Promedio temporal

Una vez alineado el micrófono 10 respecto al 8, se calcula el promedio
sample a sample:

```
mic_9[n] = ( mic_8[n] + mic_10_alineado[n] ) / 2
```

Esto es válido porque:

- Los micrófonos están **calibrados a 94 dB SPL**, por lo que sus
  niveles absolutos son comparables.
- El ángulo 80° es **equidistante** entre 70° y 90° (t = 0.5 exacto).
- Con la alineación previa por GCC-PHAT no hay cancelación de fase
  entre las dos señales al promediar.

---

## Requisitos

```
pip install numpy soundfile
```

---

## Configuración

Editá las siguientes variables al inicio del script:

| Variable | Descripción | Valor por defecto |
|---|---|---|
| `CARPETA_ENTRADA` | Ruta a la carpeta `forte/` con subcarpetas `mic8/`, `mic10/` | — |
| `DINAMICA` | Dinámica a procesar | `"forte"` |
| `MIC_FALTANTE` | Número del micrófono a generar | `9` |
| `MIC_IZQ` | Micrófono vecino izquierdo (70°) | `8` |
| `MIC_DER` | Micrófono vecino derecho (90°) | `10` |
| `MAX_DELAY_SEG` | Ventana de búsqueda del delay en GCC-PHAT | `0.05` s |

---

## Estructura de carpetas esperada

```
forte/
  mic8/
    mic_8_ang_forte_0.wav
    mic_8_ang_forte_10.wav
    ...
  mic10/
    mic_10_ang_forte_0.wav
    mic_10_ang_forte_10.wav
    ...
  mic9/   ← se crea automáticamente con los archivos generados
```

---

## Uso

```bash
python interpolar_mic9_temporal.py
```

El script imprime para cada ángulo de fuente los niveles RMS de entrada
y salida, y el delay detectado entre mic 8 y mic 10:

```
  0°  |  mic8: -25.1 dBFS  mic10: -24.8 dBFS  delay: +3 muestras  salida: -25.0 dBFS  →  mic_9_ang_forte_0.wav
 10°  |  mic8: -24.6 dBFS  mic10: -25.2 dBFS  delay: +2 muestras  salida: -24.9 dBFS  →  mic_9_ang_forte_10.wav
...
```

El nivel de salida debería quedar entre el nivel de mic 8 y mic 10. Si
difiere más de 2–3 dB, revisá que los archivos de entrada sean correctos.

---

## Limitaciones

- El método usa solo **2 puntos de soporte** (mic 8 y mic 10). Con solo
  dos puntos la interpolación es lineal — no hay curvatura del patrón polar.
  Para la mayoría de los casos esto es suficiente dado que 80° es
  equidistante entre 70° y 90°.
- El delay se detecta con **resolución de muestra entera**. Para señales
  con diferencias de fase submuestra el error es menor a 1/sr ≈ 0.02 ms
  a 44.1 kHz, lo cual es despreciable para el análisis del patrón polar.
- No modela posibles **diferencias de coloración** entre la posición 70°
  y 90° — solo el nivel y el delay.