@echo off
:: ── Build: Alineador Temporal → alineador.exe ────────────────────────────────
:: Requiere: pip install pyinstaller  (una sola vez)
::
:: Resultado: dist\Alineador.exe  (ejecutable autónomo, sin consola)

pyinstaller ^
  --onefile ^
  --windowed ^
  --name Alineador ^
  --collect-all pyqtgraph ^
  --collect-all qt_material ^
  --hidden-import sounddevice ^
  --hidden-import soundfile ^
  --hidden-import scipy.signal ^
  --hidden-import scipy.special._cython_special ^
  alineador.py

echo.
if exist dist\Alineador.exe (
    echo [OK] Listo: dist\Alineador.exe
) else (
    echo [ERROR] La compilacion fallo. Revisa el log de arriba.
)
pause
