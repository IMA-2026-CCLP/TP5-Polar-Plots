# Handoff: Rediseño visual — Polar Pattern Analyzer (PyQt6)

## Overview
**Polar Pattern Analyzer** es una app de escritorio en **PyQt6** para analizar el patrón
de directividad de un array de micrófonos. Tiene un *ribbon* global estilo Word con 4
pestañas (Archivo · Procesamiento · Notas · Directividad), tema oscuro/claro, una grilla
2×2 de visualizaciones (Plotly/pyqtgraph), un selector de banda de tercio de octava, un
dock de log y una barra de estado.

Este paquete documenta un **rediseño puramente visual** (no cambia el flujo ni la lógica):
nueva paleta, jerarquía tipográfica, acento de color, logo y pulido de espaciados. El
objetivo es que la app **se vea como el mockup** manteniendo intacto todo el comportamiento.

## About the Design Files
Los archivos `mockup/` de este bundle son una **referencia de diseño hecha en HTML** — un
prototipo navegable que muestra el look & feel buscado. **No** son código de producción para
copiar literalmente. El target real es **PyQt6 con QSS** (Qt Style Sheets), que ya es como
está construida la app.

Para acelerar, en `qt-export/` se incluyen **archivos Python drop-in ya escritos** que
reemplazan directamente a los de `app/ui/`. La tarea de Claude Code es: **aplicarlos,
verificar que la app corre, y cerrar la última brecha (tipografías) para que el resultado
en vivo coincida con el mockup.**

## Fidelity
**Alta fidelidad (hifi).** El mockup tiene colores, tipografías, medidas y estados finales.
Recrear pixel-perfect usando QSS + la estructura de widgets existente.

## Target environment
- **Lenguaje:** Python 3 · **GUI:** PyQt6
- **Estilado:** un único QSS global parametrizado por una paleta (`dict`), aplicado con
  `QApplication.setStyleSheet()`. NO hay CSS ni stylesheets por-widget (salvo excepciones
  puntuales que este rediseño justamente elimina).
- **Iconos:** `qtawesome` (FontAwesome 5) + algunos SVG en `app/ui/icons/`.
- **Plots:** Plotly (incrustado) y pyqtgraph — **NO TOCAR**, quedan igual.

## Cómo aplicar (pasos para Claude Code)
1. Reemplazar estos archivos del repo con los de `qt-export/` (mismas rutas):
   - `app/ui/theme.py`          → paletas DARK (Graphite) y LIGHT (Daylight)
   - `app/ui/styles.py`         → QSS nuevo (`get_qss(palette)`)
   - `app/ui/ribbon.py`         → ribbon con botones de acento reactivos al tema, ".wav", logo
   - `app/ui/band_selector.py`  → chips de banda estilados por QSS
   - `app/ui/icons/logo.svg`    → logo nuevo (copiar el archivo)
2. Verificar que la app levanta: `cd app && python main.py`.
3. **Cerrar la brecha de tipografías** (ver sección *Typography / fuentes*). Sin esto, la app
   cae a Segoe UI/Consolas y NO se ve igual al mockup.
4. Probar el toggle de tema (botón ☀/🌙 arriba a la derecha) en las 4 pestañas: todos los
   acentos, chips y botones deben cambiar de color correctamente.

## Qué se mantiene exactamente igual
- El flujo de 4 pestañas y todo el wiring de señales/slots (`pyqtSignal`) del ribbon.
- Los nombres públicos de atributos/métodos (`btn_compute`, `combo_theta`, `set_ma_loaded`,
  `get_dir_display_params`, etc.) — `main_window.py` depende de ellos.
- Las visualizaciones (Plotly/pyqtgraph) y toda la lógica de `core/`, `plot/`, `filterbank/`.

---

## Design Tokens

### Paleta — DARK ("Graphite", oscuro frío, acento cian)
| Token | Hex | Uso |
|---|---|---|
| `bg_base`    | `#15171c` | fondo ventana/contenido |
| `bg_panel`   | `#1c1f26` | cards / paneles |
| `bg_dark`    | `#0f1115` | sunken / inputs / sidebar |
| `text`       | `#e8eaef` | texto principal |
| `text2`      | `#969ba6` | texto secundario |
| `text_muted` | `#686d77` | texto tenue / hints |
| `accent`     | `#2dd4bf` | acento (cian) |
| `accent_ink` | `#06302b` | texto sobre acento |
| `accent_hover`| `#3ee3ce` | acento hover |
| `border`     | `#2a2e37` | bordes/divisores |
| `border2`    | `#363b46` | bordes de inputs |
| `ok` / `warn` / `err` | `#46d39a` / `#e7b15a` / `#ef6b6b` | semánticos |
| ribbon: `rb_tabs` `#1b1e24` · `rb_panel` `#1d2027` | | barra de tabs / panel |

### Paleta — LIGHT ("Daylight", claro neutro, acento índigo)
| Token | Hex | Uso |
|---|---|---|
| `bg_base`    | `#eef0f4` | fondo ventana |
| `bg_panel`   | `#ffffff` | cards |
| `bg_dark`    | `#f3f5f8` | sunken / inputs |
| `text`       | `#1b1e26` | texto principal |
| `text2`      | `#545a66` | secundario |
| `text_muted` | `#8a909c` | tenue |
| `accent`     | `#3b54d6` | acento (índigo) |
| `accent_ink` | `#ffffff` | texto sobre acento |
| `accent_hover`| `#4a62e0` | acento hover |
| `border`     | `#dfe3ea` | bordes |
| `border2`    | `#cad0db` | bordes de inputs |
| `ok` / `warn` / `err` | `#1f9d63` / `#c98a2b` / `#d65151` | semánticos |

### Typography / fuentes  ⚠ ESTO ES LO QUE FALTA PARA EL MATCH EXACTO
Stacks (definidos en `styles.py`, con fallback del sistema):
- **Títulos / headers de panel:** `Space Grotesk` → IBM Plex Sans → Segoe UI
- **UI general:** `IBM Plex Sans` → Segoe UI → Inter
- **Datos / monoespaciada (números, log, tablas, chips):** `IBM Plex Mono` → JetBrains Mono → Consolas

El sistema del usuario (Windows) **no tiene** Space Grotesk / IBM Plex, por eso cae al
fallback y no coincide. **Solución recomendada — bundlear las fuentes con la app** para que
viajen con el repo y no dependan de instalación por-máquina:

1. Crear `app/ui/fonts/` y descargar los `.ttf` (gratis, Google Fonts / OFL):
   Space Grotesk (Regular, Medium, SemiBold, Bold), IBM Plex Sans (Regular, Medium, SemiBold,
   Bold), IBM Plex Mono (Regular, Medium, SemiBold).
2. Crear `app/ui/fonts.py` con un cargador y llamarlo **antes** de aplicar el QSS, justo
   después de crear el `QApplication` en `main.py`:

```python
# app/ui/fonts.py
import os, glob
from PyQt6.QtGui import QFontDatabase

def load_bundled_fonts():
    d = os.path.join(os.path.dirname(__file__), "fonts")
    for ttf in glob.glob(os.path.join(d, "*.ttf")):
        QFontDatabase.addApplicationFont(ttf)
```
```python
# en main.py, tras: app = QApplication(sys.argv)
from ui.fonts import load_bundled_fonts
load_bundled_fonts()
```
Con las familias ya cargadas, los stacks de `styles.py` resuelven a las correctas y la app
queda idéntica al mockup. (Si se prefiere no bundlear, alternativa: instalar las 3 familias
en el sistema y reiniciar.)

### Medidas clave (del ribbon)
- Barra de pestañas: alto `30px`. Panel del ribbon: alto `100px`.
- Logo: `24×24` SVG, seguido de `10px` de espacio.
- Botones de herramienta (icon+texto): `62×68px` (algunos `60/72/84` de ancho).
- Tile de ícono: `26×26`. Inputs del ribbon: `min-height 18px`, `border-radius 5px`.
- Separadores verticales entre grupos: `1×60px`.
- Etiqueta de grupo (AUDIO, HPF, …): `8pt`, `letter-spacing 0.14em`, centrada abajo.
- Chips de banda: `46×38px`, `border-radius 7px`, mono `8.5pt`.

### Componentes y estados (resumen)
- **Botón primario / acento** (`#btn_primary`, `#btn_accent`): fondo `accent` sólido (sin
  gradiente), texto `accent_ink`; hover → `accent_hover`; disabled → fondo `border`, texto
  `text_muted`. *(El bug original: el ribbon usaba un gradiente índigo fijo que ignoraba el
  tema — ya corregido en `qt-export/ribbon.py`.)*
- **Pestaña activa:** subrayado `2px solid accent`, texto `text`.
- **Chip de banda activo** (`#band_chip:checked`): fondo `accent`, texto `accent_ink`.
- **Tab "Cargar audio":** muestra el glifo **`.wav`** (render de texto en color acento) en
  vez del ícono de carpeta.
- **Inputs numéricos / tabla / log / chips:** familia monoespaciada.

## Screens / Views
Las 4 pestañas comparten el mismo *chrome* (tab bar + ribbon + status bar). El mockup
(`mockup/Polar Analyzer App.dc.html`) es interactivo: se puede hacer clic en las pestañas y
alternar Oscuro/Claro arriba a la derecha. En el mockup, las áreas de gráficos son
**placeholders vacíos a propósito** (los plots reales no se tocan).

- **Archivo:** card "FUENTE" con toggle Audios crudos / Sesión, campos de carpeta y patrones,
  botón primario "Cargar y procesar". Ribbon: grupos AUDIO/SESIÓN y PATRÓN POLAR.
- **Procesamiento:** plot de señales (placeholder) + leyenda. Ribbon: VISTA (θ/Az con
  desplegables del **mismo ancho**), HPF, ALINEACIÓN (botones "Alinear tomas/Mics"
  **centrados**), CALIBRAR.
- **Notas:** tabla de segmentos (mono) + piano roll (placeholder). Ribbon: ESCALA, DETECCIÓN,
  MÁSCARA.
- **Directividad:** grilla 2×2 (3D, Esfera, Polar 2D, Espectro) + selector de banda en chips.
  Ribbon: CÁLCULO, NOTA, VISUALIZACIÓN, ESPECTRO, GUARDAR.

## Files
- `mockup/Polar Analyzer App.dc.html` — prototipo interactivo de alta fidelidad (referencia visual).
- `mockup/support.js` — runtime del prototipo (necesario para abrir el HTML).
- `qt-export/ui/theme.py` — paletas oscura/clara (drop-in de `app/ui/theme.py`).
- `qt-export/ui/styles.py` — QSS parametrizado (drop-in de `app/ui/styles.py`).
- `qt-export/ui/ribbon.py` — ribbon rediseñado (drop-in de `app/ui/ribbon.py`).
- `qt-export/ui/band_selector.py` — chips de banda (drop-in de `app/ui/band_selector.py`).
- `qt-export/ui/icons/logo.svg` — logo nuevo (copiar a `app/ui/icons/`).

## Assets
- `logo.svg` — generado para este rediseño (patrón polar de directividad, color = `accent`).
- Iconos restantes: `qtawesome` (FontAwesome 5), ya presente en el proyecto.
- Fuentes: Space Grotesk, IBM Plex Sans, IBM Plex Mono (Google Fonts, licencia OFL) — a
  bundlear como se describe arriba. No incluidas en este paquete (binarios .ttf).
