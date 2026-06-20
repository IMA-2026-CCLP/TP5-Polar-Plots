# runtime_hook_webengine.py
# Ejecutado por PyInstaller al arrancar el .exe — configura WebEngine antes de Qt.
import os
import sys

if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    os.environ.setdefault("QTWEBENGINEPROCESS_PATH", os.path.join(base, "QtWebEngineProcess.exe"))
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

# Desactivar JIT de numba: evita crash al arrancar en app congelada
os.environ["NUMBA_DISABLE_JIT"] = "1"
