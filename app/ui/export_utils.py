"""ui/export_utils.py — Piezas comunes de la exportación de imágenes de los 4 gráficos."""
from PyQt6.QtGui import QImage

# Ancho en píxeles a 96 DPI (escala 1×). Todas las imágenes salen con ancho = EXPORT_BASE_W * DPI / 96,
# sin importar el tamaño de la ventana; el alto sale de la proporción del gráfico en pantalla.
EXPORT_BASE_W = 720


def set_png_dpi(path: str, dpi: float) -> None:
    """Guarda el DPI en los metadatos del PNG (pHYs); sin esto los programas leen siempre 96."""
    img = QImage(path)
    if img.isNull():
        return
    dpm = int(round(dpi / 0.0254))
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    img.save(path, "PNG")


def export_pg_svg(plot_widget, path: str, dpi: float) -> None:
    """SVG vectorial de un pyqtgraph.PlotWidget con QSvgGenerator (el SVGExporter de pyqtgraph falla con
    esta versión de Qt). Ancho lógico = EXPORT_BASE_W; el alto sale de la proporción en pantalla."""
    from PyQt6.QtCore import QRect, QRectF, QSize
    from PyQt6.QtGui import QPainter, QColor
    from PyQt6.QtSvg import QSvgGenerator

    src = plot_widget.getPlotItem().sceneBoundingRect()
    w = EXPORT_BASE_W
    h = int(round(w * src.height() / max(1.0, src.width())))
    gen = QSvgGenerator()
    gen.setFileName(path)
    gen.setSize(QSize(w, h))
    gen.setViewBox(QRect(0, 0, w, h))
    gen.setResolution(96)          # el SVG es vectorial: el DPI no aplica (y con otro valor Qt escala mal el texto de los ejes)
    p = QPainter(gen)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRect(0, 0, w, h), QColor("#ffffff"))
    plot_widget.scene().render(p, QRectF(0, 0, w, h), src)
    p.end()
