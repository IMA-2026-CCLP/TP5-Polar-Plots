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

echo [3/3] Construyendo ejecutable...
pyinstaller polar_analyzer.spec --noconfirm --clean

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
