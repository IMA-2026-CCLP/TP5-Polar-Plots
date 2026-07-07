@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  build_exe.bat — Genera el ejecutable de Polar Pattern Analyzer
REM
REM  Ejecutar desde la carpeta raíz del proyecto (donde está este archivo):
REM      build_exe.bat
REM ─────────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

echo [1/3] Activando entorno virtual...
call .venv\Scripts\activate.bat

echo [2/3] Instalando PyInstaller en el entorno...
pip install pyinstaller pyinstaller-hooks-contrib --quiet

echo [3/3] Limpiando builds anteriores...
REM Se borra "a mano" en vez de usar --clean de PyInstaller: esa flag borra
REM y recrea build\ en el mismo paso, y OneDrive (que sincroniza esta carpeta
REM en vivo) choca con esa operacion rapida, dejando la carpeta a medio crear.
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Construyendo ejecutable...
pyinstaller polar_analyzer.spec --noconfirm

echo.
if exist "dist\PolarPatternAnalyzer\PolarPatternAnalyzer.exe" (
    echo  BUILD EXITOSO
    echo  Ejecutable en: dist\PolarPatternAnalyzer\PolarPatternAnalyzer.exe
    echo.
    echo  Para compartir: comprimí toda la carpeta dist\PolarPatternAnalyzer\ en un ZIP.
) else (
    echo  BUILD FALLIDO — revisar errores arriba
)

pause
