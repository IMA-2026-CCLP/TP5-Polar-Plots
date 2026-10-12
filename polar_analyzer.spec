# -*- mode: python ; coding: utf-8 -*-
"""
polar_analyzer.spec — PyInstaller spec para Polar Pattern Analyzer.
Generar el .exe: build_exe.bat (o `pyinstaller polar_analyzer.spec --noconfirm --clean`)
"""
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ('app/ui/icons', 'ui/icons'),
    ('app/ui/fonts', 'ui/fonts'),
    ('app/plot/vendor', 'plot/vendor'),      # plotly.js local (sin internet)
]
binaries = []
hiddenimports = [
    'scipy.signal',
    'soundfile',
]

# Paquetes con imports dinámicos que PyInstaller no detecta solo —
# librosa (+ numba/llvmlite) y pyqtgraph son los habituales problemáticos.
for pkg in ('librosa', 'pyqtgraph', 'numba', 'soundfile'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['app/main.py'],
    pathex=['app'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Lo que la app no usa y pesaría de más en el instalador. WebEngine (navegador interno, ~320 MB) ya no se usa: los
    # 4 gráficos son nativos. pandas / IPython / matplotlib / tkinter solo aparecen en métodos de cuaderno (Jupyter) de
    # mic_array/patron.py que la interfaz nunca llama.
    excludes=[
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineQuick', 'PyQt6.QtWebChannel',
        'PyQt6.QtQuick', 'PyQt6.QtQuickWidgets', 'PyQt6.QtQml', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
        'PyQt6.QtBluetooth', 'PyQt6.QtNfc', 'PyQt6.QtSensors',
        'PyQt6.QtSerialPort', 'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtTest', 'PyQt6.QtSql',
        'pandas', 'IPython', 'matplotlib', 'tkinter',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PolarPatternAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='app/ui/icons/logo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PolarPatternAnalyzer',
)
