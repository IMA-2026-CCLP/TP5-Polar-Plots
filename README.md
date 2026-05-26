# TP5-Polar-Plots

Lo más cómodo sería meter las carpetas Medicion_Cristian y Medicion_Juli (les saqué las tildes) acá. Están en el gitignore para que no jodan. 

- funciones.py me quedó de SyS, había cositas útiles.
- En polar.ipynb estaba probando el proceso inicial y el gráfico de patrón polar 2d en el eje 0°.
- En baloon.ipynb van las pruebas del 3d. Por ahora solo tiene un script que me pasó Gemini.

**Primero que nada habria que ver qué hacemos con los armónicos.**

## Lógica de Procesamiento
Lo que se me ocurrió es esto:

- El recorte de los audios se hace en Reaper a mano. Temporalmente los 18 mics están alineados, no es tanto laburo. Codearlo sería mucho peor.
- **Normalización de nivel**: 
    - Promediar el SPL de todas las mediciones del mic de ref o proponer cual es el nivel con el que queremos normalizar.
    - A partir de ese valor, guardar en un .csv el ajuste de nivel que debería tener cada repetición, __por banda__ (o depende que decidamos sobre los armónicos). Serian 3 columas: ángulo horizontal, banda y Offset/Ganancia que se debería sumar para alcanzar el nivel de normalización.
- **Procesamiento de los audios**: Recorrer todos los audios y extraer la data que vamos a usar para que sea manejable como DataFrame. El loop que está en polar.ipynb lo resolvería casi. Esto incluye:
    - Filtrar por tercios de octava.
    - Convertir a un único valor de SPL por banda.
    - Aplicar el ajuste de normalización de nivel. 
    - Grabar un csv los resultados (Mic, Ang Ver, Ang Hor, Frec Banda, SPL).

## Gráficos y GUI

Próximamente...

Pero con toda la data ya procesada es lo de menos.

