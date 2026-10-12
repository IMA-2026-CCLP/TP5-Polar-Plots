# Polar Pattern CCLP

Analizador de patrón polar (directividad) de voz cantada, medida con un array semicircular de micrófonos.

## Instalar (para desarrollar)

Necesitás Python 3.13 o superior (Windows).

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Correr

```
python app/main.py
```

Con el venv activado. Sin activarlo: `.venv\Scripts\python.exe app\main.py`.

## Armar el instalador de Windows

Hace falta tener el venv armado (ver arriba). Después, doble clic en:

```
construir_instalador.bat
```

Arma el `.exe` con PyInstaller, instala Inno Setup 6 con `winget` si falta, y genera
`installer_output\PolarPatternCCLP-Setup-<versión>.exe`, que es el único archivo que hay que pasar para instalar
en otra PC (no requiere Python ni permisos de administrador). Tarda unos 10 a 20 minutos.

Para rehacer solo el instalador, con el `.exe` ya armado en `dist\`: `build_installer.bat`.

La versión sale de un solo lugar: `app/version.py`.

## Uso rápido

1. **Archivo ▸ Cargar audio…** (carpeta con los WAV de la medición).
2. **Procesamiento:** filtro pasa-altos, calibración, **Filtrar 1/3 oct**, y la nivelación **Por toma** y **On Axis**.
   La vista por defecto es la matriz radial.
3. **Herramientas ▸ Segmentación por notas…** (opcional): alinear tomas, TDOA y detectar notas.
4. **Directividad:** Polar 2D, Superficie 3D, Esfera y Espectro.
5. **Archivo ▸ Guardar:** guarda la sesión `.cclp` (grilla procesada, máscara y configuración). **No guarda los audios.**
