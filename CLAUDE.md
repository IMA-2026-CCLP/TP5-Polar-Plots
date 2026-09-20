# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A PyQt6 desktop app ("Polar Pattern CCLP" / Polar Pattern Analyzer) for measuring and visualizing the polar directivity pattern of a singing voice, recorded with a 19-microphone semicircular array in an anechoic chamber (see `PIPELINE.md` for the full experimental methodology and signal-processing rationale).

## Commands

Run the app (from repo root or from `app/`, both work):
```bash
python app/main.py
# or
cd app && python main.py
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Build the Windows `.exe`:
```bash
build_exe.bat
```
This wraps `pyinstaller polar_analyzer.spec --noconfirm`. `build_exe.bat` manually `rmdir /s /q build dist` before invoking PyInstaller. If a build fails with a file-in-use error on `build/`, just delete `build/` and `dist/` and rerun.

There is no test suite, linter, or type checker configured in this repo.

## Architecture

### Entry point and import layout

`app/main.py` inserts `app/` itself onto `sys.path`, so all internal imports are rooted at `app/` (e.g. `from ui.main_window import MainWindow`, `from mic_array.patron import MicArray`), not `from app...`. `polar_analyzer.spec` mirrors this with `pathex=['app']`. Keep this in mind when adding new modules — imports inside `app/` are always relative to `app/`, never to the repo root.

`QWebEngineView` **must** be imported before the `QApplication` is constructed (see the comment in `main.py`) — this is a hard Qt requirement, not a style choice.

### UI shell: native menu + tabs + parameter rows (VituixCAD-style)

`MainWindow` hosts a `QStackedWidget` of four tab views (Preprocesamiento → Directividad, in `ui/tab_*.py`; Preprocesamiento is the home tab. Notas is not a tab: `TabNotas` plus the ribbon's `notas_page` (Escala/Detección rows) live in a non-modal `_NotasWindow` opened from Herramientas ▸ Detección de notas… Loading audio/sessions lives in the Archivo menu via `ui/file_loader.py`, not a tab; file-name patterns are set in a modal and kept in `QSettings`) under a single global top bar, `NativeRibbon` (`ui/native_ribbon.py`): a `QMenuBar`, a `QTabBar`, and one page of compact parameter rows per tab, all plain Qt widgets styled sober/flat by `ui/styles.py` + `ui/theme.py`. (It replaced an HTML/JS ribbon in a `QWebEngineView`; `QWebEngineView` is still needed for the Plotly `BalloonView`s.) `Bridge` (`ui/bridge.py`) is no longer a WebChannel object — it just holds `state` (a plain dict with the current value of every control) and the slots that build each signal's arguments from it. Widgets write `Bridge.state` directly and call those slots; `NativeRibbon` re-exposes the resulting signals for `MainWindow` to connect. Menu items and toolbar buttons share `QAction`s so enabled state stays in sync.

When changing default UI state (e.g. which panels are visible by default), the value lives in `Bridge.state`'s initial dict (widgets read their initial value from it via `_loaders`), plus any fallback default read via `.get(key, default)` downstream. `Bridge.state`'s initial value is overridden once a `.cclp` session is loaded, since `_on_ma_ready` in `main_window.py` does `bridge.state.update(loaded_ui_state)` and `NativeRibbon.set_ma_loaded` then re-syncs every widget from `state`.

### Domain model: `MicArray`

`mic_array/patron.py` defines `MicArray`, the single class the whole pipeline revolves around. It wraps a `(n_azimuth, n_theta, n_samples)` tensor plus metadata (sample rate, angles, calibration) and carries the *entire* processing pipeline as instance methods: `from_audio`/`from_tensor` (load), `hpf`, `align_takes`, `align_to_ref` (temporal alignment via onset detection + GCC-PHAT), `calibrate`/`to_spl` (SPL calibration), `detect_notes`/`extract_all_notes` (pYIN-based note segmentation, producing `self.notes: dict[str, MicArray]`), `compute_leq`/`compute_directivity` (1/3-octave analysis via `filterbank/filterbank.py`). It also carries a large set of legacy `plot_*`/`plot_*_html` methods (matplotlib/plotly-string based) from the original notebook-driven workflow — the GUI's directivity tab does **not** call these; it re-renders from the raw arrays instead (see below).

Tabs pass a shared `MicArray` instance up the chain via `ma_ready`/`ma_updated` signals; `MainWindow._on_ma_ready` is the hub that re-propagates it to every other tab via `set_ma()`. Each tab that mutates `ma` (preprocessing, calibration, note extraction) is expected to emit the (possibly same, possibly copied) instance back out.

### Directivity visualization (the most actively developed part)

`ui/tab_directividad.py` + `ui/balloon_view.py` + `plot/balloon.py` implement four simultaneous, independently-configurable Plotly views — Superficie 3D, Esfera, Polar 2D, Espectro — each a `BalloonView` (`QWebEngineView`) docked in a nested `QMainWindow` grid inside `TabDirectividad`. Key points:

- `plot/balloon.py` has one `build_*_html()` function per view type; each takes the raw `levels`/`azimuths`/`elevations`/`bands` arrays plus a free-form `style: dict` (colors, font sizes, smoothing, interpolation — whatever the "Propiedades" panel exposes) and returns either a full HTML document or a JS snippet.
- Re-renders after the first load use `Plotly.react()` in place (`update_only=True` in `_wrap_html`) rather than reloading the page, so camera angle/zoom/pan survive band changes, style edits, etc. `uirevision` in each layout must stay stable across renders for this to work.
- Per-panel "Propiedades" is a non-modal side panel (`QSplitter`, not a `QDialog`) shared across the four views, rebuilt on demand from `_ViewSection.build_properties_widget()`. Font sizes are literal pixel values from that dialog with **no** automatic rescaling on panel resize — an earlier attempt at proportional auto-scaling was removed because it made exported images diverge from what was on screen.
- Image export (`BalloonView.export_image`) drives `Plotly.toImage()` and reads the result back over a chunked `console.log` relay (`EXPORTIMG:<id>:<i>:<n>:<chunk>`) captured by the custom `_SilentPage.javaScriptConsoleMessage`, because `QWebEnginePage.runJavaScript()`'s callback does not reliably resolve a returned Promise in this environment. It falls back to a raw `QWebEngineView.grab()` screenshot if `toImage()` fails or times out.
- Right-click context menus on the 3D/Sphere WebGL canvases can't rely on Qt's native `customContextMenuRequested` (Plotly's orbit-camera controls swallow the browser's own `contextmenu` event) — they're relayed through the same console-log channel (`CONTEXTMENU:x,y`).

### Persistence formats

Two distinct on-disk formats, both NPZ under the hood:
- **`.cclp`** (`core/session.py`) — full working session: raw tensor (SPL reverted before saving), array metadata, calibration, computed directivity, extracted notes, and UI state as JSON.
- **directivity `.npz`** (`core/data_store.py`) — directivity-only results for exchange/inspection, schema documented at the top of that file. `save_results()` will use the first computed note as the "global" section if the user never computed directivity on "Todo el audio", so the file is always loadable even when only per-note directivity exists.

### Packaging

`polar_analyzer.spec` bundles `librosa`, `pyqtgraph`, `numba`, and `soundfile` via `collect_all()` in a try/except loop (these have import-time dynamic behavior PyInstaller's static analysis misses on its own). Icons and fonts are added as explicit `datas`. Output is a onedir build (`dist/PolarPatternAnalyzer/`, `_internal/` subfolder + `.exe`) — when sharing the built app, the whole folder must be zipped, not just the `.exe` (it will fail with a missing-DLL error otherwise since the internal Qt/Python DLLs live in `_internal/`).
