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


DEFAULT_COLORBAR_PT = 12.0


def get_colorbar_pt() -> float:
    """Tamaño (pt) de los valores de la escala de colores en las imágenes exportadas."""
    try:
        v = float(_settings().value("export/colorbar_pt", DEFAULT_COLORBAR_PT))
    except (TypeError, ValueError):
        return DEFAULT_COLORBAR_PT
    return max(6.0, min(40.0, v))


def set_colorbar_pt(v: float) -> None:
    _settings().setValue("export/colorbar_pt", float(v))


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


# ── Suavizado (Herramientas ▸ Suavizado…) — una sola configuración para Polar 2D, Superficie 3D
# y Esfera (antes cada gráfico tenía su propio "Suavizado"/"Interpolación" duplicado y desalineado
# en Propiedades). smoothing_method/smoothing_window/interp_deg son comunes a los 3; spline_factor
# sólo lo usan Superficie 3D/Esfera (factor de la spline 2D) e interp_kind sólo Polar 2D (tipo de
# spline 1D) — no tienen un equivalente real en los otros gráficos.
DEFAULT_SMOOTHING = dict(
    smoothing_method="gaussian", smoothing_window=3, interp_deg=2.0,
    spline_factor=0.0, interp_kind="cubic",
)


def get_smoothing_settings() -> dict:
    s = _settings()
    out = dict(DEFAULT_SMOOTHING)
    try:
        out["smoothing_method"] = str(s.value("smoothing/method", out["smoothing_method"]))
        out["smoothing_window"] = int(float(s.value("smoothing/window", out["smoothing_window"])))
        out["interp_deg"]       = float(s.value("smoothing/interp_deg", out["interp_deg"]))
        out["spline_factor"]    = float(s.value("smoothing/spline_factor", out["spline_factor"]))
        out["interp_kind"]      = str(s.value("smoothing/interp_kind", out["interp_kind"]))
    except (TypeError, ValueError):
        return dict(DEFAULT_SMOOTHING)
    return out


def set_smoothing_settings(values: dict) -> None:
    s = _settings()
    s.setValue("smoothing/method", values["smoothing_method"])
    s.setValue("smoothing/window", int(values["smoothing_window"]))
    s.setValue("smoothing/interp_deg", float(values["interp_deg"]))
    s.setValue("smoothing/spline_factor", float(values["spline_factor"]))
    s.setValue("smoothing/interp_kind", values["interp_kind"])


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


_LEGEND_ZOOM = 1.6   # factor de la muestra del trazo en el export
_LEGEND_TEXT_FACTOR = 1.25   # proporción texto de leyenda / ejes igual a la de pantalla
_WIDTH_DEFAULTS = {'line_width': 2.5, 'ring_width': 0.5, 'spoke_width': 0.5, 'axis_line_width': 3, 'err_width': 2}


def _scaled_style(style: dict, k: float, s: float = 1.0) -> dict:
    """Copia de style con los *_width (y el 'width' de cada banda comparada) multiplicados por k.

    Las plumas de pyqtgraph son "cosméticas" (ancho fijo en píxeles del dispositivo): al agrandar el
    lienzo para más DPI no acompañan solas, y las líneas se ven cada vez más finas. Compensamos subiendo
    el ancho en la misma proporción que los píxeles, para que el grosor físico (en cm) no cambie.
    Se fija siempre (con el mismo valor por defecto que usa el pincel) porque la mayoría de estas claves
    no están en `style` salvo que el usuario las haya tocado en Propiedades."""
    if k == 1 and s == 1:
        return style
    out = dict(style)
    for key, default in _WIDTH_DEFAULTS.items():
        out[key] = float(out.get(key, default)) * k * s
    for key in list(out):                       # fuentes: escala del gráfico (el render ya aplica el DPI)
        if key.endswith('_font_size') and key != 'legend_font_size':
            out[key] = float(out[key]) * s
    # la leyenda es HTML: no acompaña el escalado del render, va con el DPI explícito
    # leyenda más grande en el export (texto y muestra del trazo) para que se vean bien los tipos de línea
    # el texto de la leyenda (HTML) sale más chico que el de los ejes al exportar: se corrige a la proporción de pantalla
    out['legend_font_size'] = float(out.get('legend_font_size', 12)) * k * s * _LEGEND_TEXT_FACTOR
    out['legend_sample_scale'] = s * _LEGEND_ZOOM   # la muestra del trazo, en unidades del gráfico (el render ya aplica el DPI)
    return out


def _paste_legend(clone, leg, img, k, margin: float = 10.0) -> None:
    """Dibuja la leyenda a mano (nombre, color y tipo de línea de cada banda) y la pega en la esquina
    superior derecha de la imagen, en el espacio libre a la derecha del círculo."""
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
    from pyqtgraph import functions as fn
    st = clone._style
    fs = float(st.get('legend_font_size', 12))                 # px de dispositivo
    sample_len = 20.0 * float(st.get('legend_sample_scale', 1.0)) * k
    gap = 6.0 * k
    row_h = fs * 1.5
    font = QFont("Segoe UI")
    font.setPixelSize(max(1, int(round(fs))))
    fm = QFontMetricsF(font)
    rows = [(sample.item.opts['pen'], label.text) for sample, label in leg.items]
    if not rows:
        return
    text_w = max(fm.horizontalAdvance(t) for _, t in rows)
    total_w = sample_len + gap + text_w
    total_h = row_h * len(rows)
    x0 = img.width() - total_w - margin * k
    y0 = margin * k
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    for i, (pen_opt, text) in enumerate(rows):
        y = y0 + i * row_h + row_h / 2
        p.setPen(fn.mkPen(pen_opt))
        p.drawLine(QPointF(x0, y), QPointF(x0 + sample_len, y))
        p.setPen(QColor('#000000'))
        p.drawText(QPointF(x0 + sample_len + gap, y + fm.ascent() / 2 - fm.descent() / 2), text)
    p.end()


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
    s = W / max(1.0, float(view.width()))   # lo que se ve en pantalla (el viewport configurado) se exporta con esa proporción
    if getattr(clone, '_compare_styles', None):   # Polar 2D: bandas comparadas, mismo motivo
        clone._compare_styles = {b: {**st, 'width': float(st.get('width', 2)) * k * s}
                                  for b, st in clone._compare_styles.items()}
    try:
        QApplication.processEvents()
        # proporción igual a la pantalla: lo que se achica el gráfico al tamaño físico se achica también el texto y las líneas
        if hasattr(clone, '_tick_font_size'):
            clone._tick_font_size = float(view._tick_font_size) * s
        clone.set_style(_scaled_style(view._style, k, s))   # también aplica estilo de ejes/grilla y vuelve a dibujar
        QApplication.processEvents()
        if fmt == 'svg':
            export_pg_svg(clone._plot, path, W, H)
        else:
            # Píxeles EXACTOS = tamaño fijo × DPI/96 (el ImageExporter usa la proporción del PlotItem, no la del lienzo)
            from PyQt6.QtCore import QRectF
            from PyQt6.QtGui import QColor, QPainter
            img = QImage(int(round(W * k)), int(round(H * k)), QImage.Format.Format_ARGB32)
            img.fill(QColor("#ffffff"))
            # la leyenda se dibuja aparte y se pega a la derecha del círculo (como la barra de color 3D)
            leg = getattr(clone, '_legend', None)
            had_leg = leg is not None and leg.isVisible()
            if had_leg:
                leg.setVisible(False)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            # se copia el widget completo (como se ve en pantalla), no sólo el área del gráfico
            src = clone._plot.mapToScene(clone._plot.viewport().rect()).boundingRect()
            clone._plot.scene().render(p, QRectF(0, 0, img.width(), img.height()), src)
            p.end()
            if had_leg:
                leg.setVisible(True)
                _paste_legend(clone, leg, img, k)
            img.save(path)
            set_png_dpi(path, dpi)
    finally:
        clone.hide()
        clone.deleteLater()
