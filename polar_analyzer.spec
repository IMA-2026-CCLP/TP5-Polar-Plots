# polar_analyzer.spec — PyInstaller spec para Polar Pattern Analyzer
#
# Uso:
#   .venv\Scripts\pyinstaller.exe polar_analyzer.spec
#
# Requiere (instalados en .venv):
#   pip install pyinstaller pyinstaller-hooks-contrib
#
# Salida: dist\PolarPatternAnalyzer\  (carpeta lista para comprimir y compartir)

from PyInstaller.utils.hooks import collect_all, collect_data_files
import sys, os

block_cipher = None

# ── Recolectar PyQt6 completo (WebEngine incluído) ─────────────────────────────
# collect_all trae datos, binarios e hiddenimports de cada paquete
pyqt_datas, pyqt_bins, pyqt_hidden = [], [], []
for pkg in [
    "PyQt6",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngine",
]:
    d, b, h = collect_all(pkg)
    pyqt_datas  += d
    pyqt_bins   += b
    pyqt_hidden += h

# ── Íconos de la UI ────────────────────────────────────────────────────────────
app_datas = [
    (os.path.join("app", "ui", "icons"), os.path.join("ui", "icons")),
]

# ── Fix QtWebEngineProcess: copiar donde Qt lo busca en PyInstaller 6+ ─────────
# PyInstaller lo deja en PyQt6/Qt6/bin/ pero Qt lo busca en _internal/
import shutil, glob as _glob
_wep_src = os.path.join(
    ".venv", "Lib", "site-packages", "PyQt6", "Qt6", "bin", "QtWebEngineProcess.exe"
)
if os.path.exists(_wep_src):
    app_datas.append((_wep_src, "."))  # copia a la raíz de _internal

# ── Recolectar pyqtgraph (editor F0 interactivo) ──────────────────────────────
try:
    pyqg_datas, pyqg_bins, pyqg_hidden = collect_all("pyqtgraph")
    app_datas   += pyqg_datas
    pyqt_bins   += pyqg_bins
    pyqt_hidden += pyqg_hidden
except Exception:
    pass

# ── Datos adicionales de librosa (archivos de parámetros de audio) ─────────────
try:
    librosa_datas, _, _ = collect_all("librosa")
    app_datas += librosa_datas
except Exception:
    pass

# ── Hidden imports que PyInstaller no detecta automáticamente ──────────────────
hidden = pyqt_hidden + [
    # PyQt6 WebEngine
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineQuick",
    "PyQt6.QtPositioning",
    "PyQt6.sip",
    # Audio / científico
    "librosa",
    "librosa.core",
    "librosa.effects",
    "librosa.feature",
    "librosa.filters",
    "librosa.util",
    "soundfile",
    "soxr",
    "scipy",
    "scipy.signal",
    "scipy.interpolate",
    "scipy.spatial",
    "sklearn",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._partition_nodes",
    # numba excluido intencionalmente — librosa funciona sin él
    # Plotly (usado como HTML embebido)
    "plotly",
    "plotly.graph_objects",
    "plotly.express",
    # pyqtgraph — backend Qt6 (solo widgets 2D, sin PyOpenGL)
    "pyqtgraph",
    "pyqtgraph.graphicsItems",
    "pyqtgraph.widgets",
]

a = Analysis(
    [os.path.join("app", "main.py")],
    pathex=[os.path.join(os.getcwd(), "app")],
    binaries=pyqt_bins,
    datas=app_datas + pyqt_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook_webengine.py"],
    excludes=[
        # Desarrollo — no usados en runtime
        "jupyter", "ipython", "ipykernel", "debugpy",
        "matplotlib", "tkinter",
        # numba: librosa puede funcionar sin él (solo algunas operaciones son más lentas)
        "numba", "llvmlite",
        # sklearn: solo si no usás clustering/ML en el pipeline
        # "sklearn",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PolarPatternAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX puede romper DLLs de Qt — dejarlo en False
    console=True,       # DEBUG: mostrar errores — cambiar a False para release
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("app", "ui", "icons", "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PolarPatternAnalyzer",
)
