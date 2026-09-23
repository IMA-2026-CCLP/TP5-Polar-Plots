"""ui/export_utils.py — Piezas comunes de la exportación de imágenes de los 4 gráficos.

Modelo: cada imagen tiene un TAMAÑO FÍSICO fijo (ancho × alto en cm, configurable en Opciones ▸ Gráficos ▸ Imágenes)
y el DPI sólo define cuántos píxeles tiene (calidad): píxeles = cm / 2,54 × DPI. Por defecto 16 × 10 cm, la
misma proporción que tiene cada gráfico en la grilla de 4, y con las fuentes de 12 px (≈ 9 pt impresos).
"""
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QStandardPaths, Qt
from PyQt6.QtGui import QImage

DEFAULT_SIZE_CM = (16.0, 10.0)
DEFAULT_DPI = 300
SIZE_PRESETS = [                       # (nombre, ancho cm, alto cm)
    ("Pantalla / informe (16 × 10 cm)", 16.0, 10.0),
    ("Columna simple de paper (8,5 × 6 cm)", 8.5, 6.0),
    ("Doble columna de paper (17 × 10 cm)", 17.0, 10.0),
    ("Diapositiva 16:9 (24 × 13,5 cm)", 24.0, 13.5),
    ("Cuadrada (12 × 12 cm)", 12.0, 12.0),
]


def _settings() -> QSettings:
    return QSettings("AcousticTools", "PolarAnalyzerV2")


def get_export_size_cm() -> tuple[float, float]:
    s = _settings()
    try:
        w = float(s.value("export/width_cm", DEFAULT_SIZE_CM[0]))
        h = float(s.value("export/height_cm", DEFAULT_SIZE_CM[1]))
    except (TypeError, ValueError):
        return DEFAULT_SIZE_CM
    return max(3.0, min(60.0, w)), max(3.0, min(60.0, h))


def set_export_size_cm(w: float, h: float) -> None:
    s = _settings()
    s.setValue("export/width_cm", float(w))
    s.setValue("export/height_cm", float(h))


def get_last_export_dir() -> str:
    """Última carpeta usada para guardar imágenes (persiste entre sesiones vía QSettings).

    La primera vez (sin nada guardado todavía) usa Documentos, o Escritorio/home si no hay
    Documentos en el sistema — nunca la carpeta del programa."""
    saved = str(_settings().value("export/last_dir", ""))
    if saved and Path(saved).is_dir():
        return saved
    for loc in (QStandardPaths.StandardLocation.DocumentsLocation,
                QStandardPaths.StandardLocation.DesktopLocation,
                QStandardPaths.StandardLocation.HomeLocation):
        d = QStandardPaths.writableLocation(loc)
        if d:
            return d
    return ""


def set_last_export_dir(folder: str) -> None:
    _settings().setValue("export/last_dir", folder)


def get_export_defaults() -> tuple[int, str]:
    """(DPI por defecto, formato por defecto) del diálogo de exportación."""
    s = _settings()
    try:
        dpi = int(float(s.value("export/dpi", DEFAULT_DPI)))
    except (TypeError, ValueError):
        dpi = DEFAULT_DPI
    fmt = str(s.value("export/format", "png"))
    return max(72, min(1200, dpi)), fmt if fmt in ("png", "svg") else "png"


def set_export_defaults(dpi: int, fmt: str) -> None:
    s = _settings()
    s.setValue("export/dpi", int(dpi))
    s.setValue("export/format", fmt)


def logical_px(cm: float) -> int:
    """Centímetros → píxeles CSS/lógicos a 96 dpi (el tamaño del 'lienzo' al que se le aplica la escala del DPI)."""
    return int(round(cm / 2.54 * 96))


def set_png_dpi(path: str, dpi: float) -> None:
    """Guarda el DPI en los metadatos del PNG (pHYs); sin esto los programas leen siempre 96."""
    img = QImage(path)
    if img.isNull():
        return
    dpm = int(round(dpi / 0.0254))
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    img.save(path)                 # formato por extensión (png/jpg/webp)


def export_pg_svg(plot_widget, path: str, w: int, h: int) -> None:
    """SVG vectorial de un pyqtgraph.PlotWidget con QSvgGenerator (el SVGExporter de pyqtgraph falla con
    esta versión de Qt). w×h = tamaño lógico del lienzo."""
    from PyQt6.QtCore import QRect, QRectF, QSize
    from PyQt6.QtGui import QPainter, QColor
    from PyQt6.QtSvg import QSvgGenerator

    src = plot_widget.getPlotItem().sceneBoundingRect()
    gen = QSvgGenerator()
    gen.setFileName(path)
    gen.setSize(QSize(w, h))
    gen.setViewBox(QRect(0, 0, w, h))
    gen.setResolution(96)          # vectorial: el DPI no aplica (y con otro valor Qt escala mal el texto de los ejes)
    p = QPainter(gen)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRect(0, 0, w, h), QColor("#ffffff"))
    plot_widget.scene().render(p, QRectF(0, 0, w, h), src)
    p.end()


_WIDTH_DEFAULTS = {'line_width': 2.5, 'ring_width': 1, 'spoke_width': 1, 'axis_line_width': 3, 'err_width': 2}


def _scaled_style(style: dict, k: float) -> dict:
    """Copia de style con los *_width (y el 'width' de cada banda comparada) multiplicados por k.

    Las plumas de pyqtgraph son "cosméticas" (ancho fijo en píxeles del dispositivo): al agrandar el
    lienzo para más DPI no acompañan solas, y las líneas se ven cada vez más finas. Compensamos subiendo
    el ancho en la misma proporción que los píxeles, para que el grosor físico (en cm) no cambie.
    Se fija siempre (con el mismo valor por defecto que usa el pincel) porque la mayoría de estas claves
    no están en `style` salvo que el usuario las haya tocado en Propiedades."""
    if k == 1:
        return style
    out = dict(style)
    for key, default in _WIDTH_DEFAULTS.items():
        out[key] = float(out.get(key, default)) * k
    return out


def export_pg_view(view, path: str, dpi: float, fmt: str = 'png', size_cm=None) -> None:
    """Exporta una vista pyqtgraph (Polar 2D / Espectro) a un tamaño físico fijo.

    Se re-renderiza en una COPIA fuera de pantalla con el tamaño del lienzo (no en el panel visible, que tiene el
    tamaño que le dé la ventana): así el resultado no depende de la ventana y no hay que tocar el layout."""
    from PyQt6.QtWidgets import QApplication

    w_cm, h_cm = size_cm or get_export_size_cm()
    W, H = logical_px(w_cm), logical_px(h_cm)
    k = dpi / 96.0

    clone = type(view)()
    for key, v in view.__dict__.items():          # estado de datos/estilo (no los widgets)
        if not isinstance(v, QObject):
            setattr(clone, key, v)
    clone.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    clone.resize(W, H)
    clone.show()
    if k != 1 and getattr(clone, '_compare_styles', None):   # Polar 2D: bandas comparadas, mismo motivo
        clone._compare_styles = {b: {**st, 'width': float(st.get('width', 2.5)) * k}
                                  for b, st in clone._compare_styles.items()}
    try:
        QApplication.processEvents()
        clone.set_style(_scaled_style(view._style, k))   # también aplica estilo de ejes/grilla y vuelve a dibujar
        QApplication.processEvents()
        if fmt == 'svg':
            export_pg_svg(clone._plot, path, W, H)
        else:
            # Píxeles EXACTOS = tamaño fijo × DPI/96 (el ImageExporter usa la proporción del PlotItem, no la del lienzo)
            from PyQt6.QtCore import QRectF
            from PyQt6.QtGui import QColor, QPainter
            img = QImage(int(round(W * k)), int(round(H * k)), QImage.Format.Format_ARGB32)
            img.fill(QColor("#ffffff"))
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            clone._plot.scene().render(p, QRectF(0, 0, img.width(), img.height()),
                                       clone._plot.getPlotItem().sceneBoundingRect())
            p.end()
            img.save(path)
            set_png_dpi(path, dpi)
    finally:
        clone.hide()
        clone.deleteLater()
