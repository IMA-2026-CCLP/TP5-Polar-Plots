Bugs o errores:
- Bug: Al estar en patrón 3D (tanto superficie como esfera), si haces click izquierdo para deslizarte si o si te aparece la lista de opciones, luego de abrirse la lista de opciones si solamente queres salir y no apretar nada se abre automáticamente un menú de comparar bandas.
- Bug: No debería de haber menú comparar bandas para los 3D, tampoco se puede acceder desde la lista de opciones haciendo click izquierdo.
- Error: El menú de comparar bandas de los 3D dice "Comparar bandas -- Polar 2D".
- Bug: El único color que varía es el de Viridis, todos los demás los plotea con el mismo color (Calculo que debe ser Plasma, que está por default). Para mi no hace falta intentar que plotee con tantas opciones, con que tenga 2 alcanza.
- Bug: El gráfico de superficie 3D aparece en blanco un buen rato cuando lo activas, no estoy seguro si solo tenés que esperar o si hace falta cambiar de bandas para que se refresque y aparezca (nunca me dió la paciencia para solo esperar). Puede ser que lo empiece a calcular recién cuando lo activas, no cuando das a calcular desde el principio.
- Error: Corregir que en la parte de Directividad, el menú desplegable de Bandas dice "1/3" y "octava", habría que homogeneizar nomenclatura
- Bug: En la parte de "Directividad", una vez que hiciste el cálculo de los gráficos, si querés cambiar el tema de la interfaz no cambia el fondo de los gráficos.
- Error: Acordate de en algún momento ir actualizando el número de versión. Para los cambios boludos que fuimos haciendo tranquilamente se podría agregar un dígito más, tipo "Versión 4.0.4" en vez de 4.4 (TKM)

Ideas de mejoras:
- En la pestaña de archivo, que por default no aparezca el path de Abel en la sección "Carpeta de audios:"
- Que la pestaña de inicio cuando abrís el soft no sea "Directividad" sino "Archivo"
- Que se pueda plotear sin necesidad de realizar una calibración SPL (posible normalización a secas? Potenciales errores en el histograma de espectro)
- Dentro de las opciones de "Vista" para la esfera agregaría Isométrica, igual se puede configurar esa vista apretando en "Reset camera to default" dentro de las opciones que aparecen arriba a la derecha de los gráficos pero intentaría que ese menú de opciones no se viera.
- Habría que mejorar el export de gráficos para que no puedas seleccionar solo DPI sino también dimensiones del gráfico.
- Habría que mejorar la visibilidad de la sección "Notas", la parte de la máscara y de la detección de notas se solapan mucho, o que se pueda ver de a una sola o que la tabla de máscaras aparezca como flotante. Daría prioridad a la visibilidad del gráfico de las notas en tiempo.
- Primero pensé que era un bug, pero en la parte "Procesamiento" no queda claro el tema del ajuste del eje y en la parte vista, para marcar "dB" se tiene que marcar "Envolvente", si desmarcas los dos, aparece un eje de amplitud random que imagino que deben de ser los valores de los array en general, pero tampoco está esa opción como seleccionable, es más un easter egg que otra cosa. Me fijaría si se puede hacer que si o si esté seleccionada una opción y agregar una de "Amplitud".
- En "Procesamiento", la parte para alinear tomas, tiene la opción de "Umbral" pero no especifica la unidad, se que es dB, pero no está escrito ni claro si se podría usar un valor de umbral que no sea dB (Por ejemplo si estuviera con la vista en Envolvente)
- En la sección de "Notas" está la parte de escala, pero si abris la parte de "Editar", te aparecen las notas, no por escalas, creo que se podría agregar como una clasificación interna en la ventana flotante que sea para agregar escalas con las notas que se te canten o que te permita agregar o quitar notas de una escala existente.
- De alguna forma se podría agregar una base de datos personalizada para la parte de escalas?
- En la parte de "Archivo" estaría bien aclarar que sería {MIC} y {H} por si quisiera cargar archivos que no tienen un choto que ver con nuestras mediciones, por ejemplo una medición de patrón polar de Electro.

Dudas personales:
- Se puede no poner micrófono de referencia, calibrar las tomas y que se plotee igual?
- En ese caso no habría alineación posible? O se podría a partir de un micrófono random?