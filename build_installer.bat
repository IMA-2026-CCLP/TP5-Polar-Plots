@echo off
REM ---------------------------------------------------------------------------
REM  build_installer.bat - Genera el instalador (Setup) de Polar Pattern CCLP
REM
REM  Requisitos: 1) haber corrido build_exe.bat (existe dist\PolarPatternAnalyzer\)
REM              2) Inno Setup 6 instalado (winget install JRSoftware.InnoSetup)
REM
REM  Resultado: installer_output\PolarPatternCCLP-Setup-VERSION.exe
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

if not exist "dist\PolarPatternAnalyzer\PolarPatternAnalyzer.exe" (
    echo No existe dist\PolarPatternAnalyzer. Corre primero build_exe.bat
    exit /b 1
)

REM Version: unica fuente en app\version.py
for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'app'); import version; print(version.__version__)"') do set APPVER=%%v

set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" (
    echo No se encontro Inno Setup 6. Instalalo con: winget install JRSoftware.InnoSetup
    exit /b 1
)

echo Compilando instalador v%APPVER% ...
"%ISCC%" /Qp /DAppVersion=%APPVER% installer.iss
if errorlevel 1 (
    echo  INSTALADOR FALLIDO
    exit /b 1
)
echo.
echo  Listo: installer_output\PolarPatternCCLP-Setup-%APPVER%.exe
