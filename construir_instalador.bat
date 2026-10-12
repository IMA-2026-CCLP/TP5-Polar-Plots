@echo off
REM ---------------------------------------------------------------------------
REM  construir_instalador.bat - Arma TODO: el .exe y el instalador de Windows.
REM
REM  Uso: doble clic, o desde PowerShell en esta carpeta:   .\construir_instalador.bat
REM
REM  Pasos: 1) prepara el entorno  2) arma el .exe con PyInstaller
REM         3) instala Inno Setup 6 si no esta (winget)  4) arma el instalador
REM  Resultado: installer_output\PolarPatternCCLP-Setup-VERSION.exe
REM  Tarda unos 10 a 20 minutos y usa cerca de 1 GB de disco.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"
setlocal

echo.
echo ===== [1/4] Entorno =====
if not exist ".venv\Scripts\python.exe" (
    echo No hay entorno virtual: creandolo e instalando dependencias...
    py -m venv .venv
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -m pip install pyinstaller pyinstaller-hooks-contrib --quiet
if errorlevel 1 goto :error

for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'app'); import version; print(version.__version__)"') do set APPVER=%%v
if "%APPVER%"=="" (
    echo No se pudo leer la version de appersion.py
    goto :error
)
echo Version de la app: %APPVER%

echo.
echo ===== [2/4] Armando el .exe (varios minutos) =====
REM Se borra a mano (sin --clean de PyInstaller): OneDrive choca con el borrado rapido de build\
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
".venv\Scripts\python.exe" -m PyInstaller polar_analyzer.spec --noconfirm
if not exist "dist\PolarPatternAnalyzer\PolarPatternAnalyzer.exe" goto :error
echo .exe listo: dist\PolarPatternAnalyzer\PolarPatternAnalyzer.exe

echo.
echo ===== [3/4] Inno Setup 6 =====
call :buscar_iscc
if "%ISCC%"=="" (
    echo Inno Setup no esta instalado: instalandolo con winget...
    winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
    call :buscar_iscc
)
if "%ISCC%"=="" (
    echo No se pudo instalar Inno Setup. Instalalo a mano desde https://jrsoftware.org/isdl.php y volve a correr este archivo.
    goto :error
)
echo Usando: %ISCC%

echo.
echo ===== [4/4] Armando el instalador =====
"%ISCC%" /Qp /DAppVersion=%APPVER% installer.iss
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  LISTO
echo  Instalador: installer_output\PolarPatternCCLP-Setup-%APPVER%.exe
echo  Es el unico archivo que hay que pasar para instalar en otra PC.
echo ============================================================
explorer installer_output
pause
exit /b 0

:buscar_iscc
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
exit /b 0

:error
echo.
echo ============================================================
echo  FALLO: revisa el mensaje de error de arriba.
echo ============================================================
pause
exit /b 1
