# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A PyQt6 desktop app ("Polar Pattern CCLP") for measuring and visualizing the polar directivity pattern of a singing voice, recorded with a 19-microphone semicircular array in an anechoic chamber (see `PIPELINE.md` and `PROCESAMIENTO_Y_FISICA.md` for the experimental methodology and signal-processing rationale). The meaning of "CCLP" is deliberately left unexplained — do not invent one.

## Commands

```bash
python app/main.py                 # run (from repo root or from app/)
pip install -r requirements.txt    # dependencies
construir_instalador.bat           # builds the .exe (PyInstaller) AND the Windows installer (Inno Setup, installed via winget if missing)
build_installer.bat                # only the installer, from an existing dist\PolarPatternAnalyzer\
```

Output of the full build: `installer_output/PolarPatternCCLP-Setup-<version>.exe` (per-user install, no admin, Start-menu entry, uninstaller). The version comes from `app/version.py` (single source: window title, About box, installer). Keep `.bat` files ASCII with CRLF line endings, otherwise `cmd` misparses them. `build/` and `dist/` are generated (and git-ignored); never delete them while a build may be running.

There is no test suite, linter, or type checker. Verify UI work by building the real `MainWindow` with `QT_QPA_PLATFORM=offscreen` and a synthetic `MicArray`, and measure geometries instead of guessing.

## Architecture

### Entry point and import layout

`app/main.py` puts `app/` on `sys.path`, so all internal imports are rooted at `app/` (`from ui.main_window import MainWindow`, `from mic_array.patron import MicArray`), never `from app...`. `polar_analyzer.spec` mirrors this with `pathex=['app']`. Qt WebEngine is **no longer used anywhere**: all four plots are native (`ui/balloon_view.py` and the Plotly HTML builders in `plot/balloon.py` are dead code). Do not reintroduce it — it added >300 MB to the installer. `main.py` still sets `AA_ShareOpenGLContexts` before creating the `QApplication` (needed by the pyqtgraph.opengl views).

### UI shell

Two tabs (`Procesamiento`, `Directividad`) under one global top bar, `NativeRibbon` (`ui/native_ribbon.py`: a `QMenuBar` + a `QTabBar`). `MainWindow` (`ui/main_window.py`) hosts a `QStackedWidget` with `TabPreprocesamiento` and `TabDirectividad`, a movable left dock "Parámetros" (a stacked page per tab) with the **Log** dock stacked below it (visible by default), and the status bar (one busy/progress indicator fed by `core.worker.activity`).

Menus: **Archivo** (Cargar audio…, Patrones de archivos…, Cargar / Guardar / Guardar como sesión, Exportar), **Ver**, **Herramientas** (Segmentación por notas…, Guardar/Cargar máscara), **Opciones** (graphs, images, palette), **Ayuda**.

`Bridge` (`ui/bridge.py`) only holds `state`, a plain dict with the value of every control, plus the slots that turn it into signals. Widgets write `Bridge.state` directly. Default UI values live in `Bridge.state`'s initial dict (controls read them through `_loaders`). `Bridge.state` is overridden when a session is loaded (`apply_ui_state`).

Long operations run in `core.worker.Worker` threads (set `worker.label` before `start()`). `mic_array` functions report progress through `patron.progress_callback`; when several things are computed in a row use `tab_directividad.compute_bands_all()` so there is ONE 0–100 % bar for the whole job.

**Procesamiento**: the center shows a view selector — **Matriz radial** (default; `ui/matrix_dialog.py`, ring × sector grid with cell replacement by mirror, **Corregir ganancia**, color scale), dB, Envolvente or Amplitud (`WaveformEditorWidget`). With the matrix, the "Vista" selector moves into the matrix row next to "Muestra" and "Frecuencia". **Muestra** (Toda la muestra / each extracted note) is mirrored in the Directividad panel through `state['nota']`. The left panel has: Señal (θ/azimut, only for signal views), Filtro y calibración (HPF, Calibración, Filtrar 1/3 oct in a wrapping `FlowLayout`), Nivelación (**Por toma**, **On Axis**), Interpolación, Suavizado. Buttons that finished are tinted light blue and their tooltip says "Ya aplicado" (`NativeRibbon.mark_done` / `clear_done`, cleared when new audio is loaded).

**Segmentación por notas** (Herramientas ▸ Segmentación por notas…): a non-modal dialog (`TabNotas`) with three steps as tabs — *1 - Alineación entre tomas* (onset; dB view of the reference mic, all takes, draggable cursor), *2 - TDOA* (GCC-PHAT between the reference and the array; one azimuth at a time; replaced channels drawn dashed), *3 - Segmentación* (scale, detection, F0 editor + segments table, Extraer notas). The GCC-PHAT button stays disabled until the takes were aligned. Before opening it asks about a saved mask (`MainWindow._ask_mask`). Extracting notes computes the 1/3-octave bands of every note and the full sample in the same worker (one progress bar) and the notes inherit the full sample's Por toma / On Axis (`TabDirectividad.inherit_note_corrections`).

### Domain model: `MicArray`

`mic_array/patron.py`: wraps a `(n_azimuth, n_theta, n_samples)` tensor plus metadata and carries the whole pipeline (`from_audio`, `hpf`, `align_takes`, `align_to_ref`, `calibrate`/`to_spl`, `detect_notes`/`extract_all_notes`, `compute_leq_bands`, `apply_take_correction_bands`, `normalize_onaxis`). Many legacy `plot_*` methods remain for notebooks; the GUI never calls them. Things to remember:

- **Thresholds are in the scale shown on screen**: dB SPL when the audio is calibrated (tensor in Pa), dBFS otherwise (`_thr_offset_db`). When the audio becomes SPL the UI shifts the onset/TDOA thresholds by the reference mic's calibration.
- **Alignment is recorded** (`align_takes_shifts`, `align_ref_taus`, `align_ref_theta`, accumulated per azimuth) so a mask can replay it without recomputing (`apply_alignment`).
- **Mirror replacements** (matrix) are registered in `_mirror_cells` {(az, mic): (src_az, src_mic)} and `_mirror_src`. They are applied to the leq grid *and* to the audio, the per-take correction uses the source take's delta, GCC-PHAT excludes replaced channels from its average, and `reapply_mirrors()` re-copies them from the (already aligned) source after every alignment. Ctrl+Z undoes them.
- **Corregir ganancia** rewrites the WAVs in the audio folder after copying the originals to `Originales_respaldo/` (only if not already there), applies the same gain to memory and to the computed levels, and is undoable with Ctrl+Z (the undo stack stores the previous file bytes).

### Directivity visualization

`ui/tab_directividad.py` has four views in a fixed 2×2 grid, each a `_ViewSection`: Superficie 3D and Esfera (`ui/gl3d_view.py`, pyqtgraph.opengl, `GL3DView`), Polar 2D (`ui/polar2d_view.py`), Espectro (`ui/spectrum_view.py`). All share the same API subset so they are polymorphic (`_VIEW_CLASS_BY_MODE`). Notes:

- **Symmetry** (`core/symmetry_utils.apply_symmetry`, panel group "Simetría") applies to every view: left↔right maps cell (θ, giro) to (180°−θ, 180°−giro) keeping the θ ≤ 90° side; up↔down adds negative elevations as the mirror of the positive ones (only visible in the vertical-plane Polar 2D, the 3D views show the upper hemisphere only).
- **Color scales** (matrix, Superficie 3D, Esfera) label the *borders* between color steps, always without decimals. Propiedades ▸ Escala has "Escala automática" (color and balloon range follow the band's min/max; 3D starts automatic, Esfera with −16…4) and "Paso de la escala (dB)" (default 1). 3D starts without the hemisphere grid.
- Image export re-renders at a fixed physical size in cm (Opciones ▸ Gráficos ▸ Imágenes), never a screenshot. Right-click uses a plain Qt `eventFilter`.
- `plot/balloon.py` still holds the shared math (`_build_hemisphere_grid`, `compute_polar2d_ring`, palettes); `plotly` is only used for its color scales.

### Persistence

One session format, **`.cclp`** (`core/session.py` → `core/data_store.py`): an NPZ with the processed grid (full sample and each note, `_save_from_grids`), the reference spectra for the Espectro view, the mask (segments + alignment) in `metadata['view']['mask']`, the plot config and the whole `Bridge.state`. It always saves *what is on screen* (not stale results of an old Calcular). It does **not** save audio: the user is warned on save and on load, and to reprocess must load the WAVs again. Old `.gcclp` (grid) and `.msk` (mask) files can still be opened (Cargar session / Cargar máscara). Guardar/Guardar como are enabled as soon as audio is loaded. `save_results()` opens the file handle itself so numpy does not append `.npz`.

`core/scales.py` holds the musical scale library (built-in + per-user JSON in `%APPDATA%/PolarPatternCCLP/scales.json`); `ui/scale_dialog.py` edits it.

### Packaging

`polar_analyzer.spec` bundles librosa, pyqtgraph, numba and soundfile with `collect_all()` and explicitly **excludes** WebEngine/Quick/Qml/Pdf and pandas/IPython/matplotlib/tkinter (only notebook-only methods use them). `QtMultimedia` is needed (take playback) — do not exclude it. Output is a onedir build; the installer compresses `dist/PolarPatternAnalyzer/`.

## UI rules learned the hard way

- **Never use `QSpinBox`/`QDoubleSpinBox`** (explicit user instruction): use `_NumEdit` (plain text) or a `QComboBox`.
- Never assume a layout width: measure `minimumSizeHint()` and the real `geometry()` offscreen. `QComboBox.minimumSizeHint()` ignores `setFixedWidth()`. A `QGridLayout` does not wrap rows by itself — use `ui.widgets.FlowLayout` when controls must wrap.
- The left dock must never get a horizontal scrollbar; make the dock wider instead (`setMinimumWidth` survives, `resizeDocks` alone does not).
- Do not stretch action buttons to the full row width unless asked.
- Reply to the user in plain Spanish, without code, and ask before doing anything expensive.
