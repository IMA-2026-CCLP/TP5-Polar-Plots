"""
make_icon.py — Genera logo.ico a partir de logo.svg.
Ejecutar UNA SOLA VEZ desde la raíz del proyecto:
    .venv\Scripts\python.exe make_icon.py
"""
import sys, os, subprocess

# Instalar Pillow si no está
try:
    from PIL import Image
except ImportError:
    print("Instalando Pillow...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'Pillow', '--quiet'])
    from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QPixmap, QPainter, QImage
from PyQt6.QtCore import Qt

SVG_PATH = os.path.join('app', 'ui', 'icons', 'logo.svg')
ICO_PATH = os.path.join('app', 'ui', 'icons', 'logo.ico')

app = QApplication(sys.argv)
renderer = QSvgRenderer(SVG_PATH)

sizes = [16, 32, 48, 64, 128, 256]
pil_images = []

for size in sizes:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()

    qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = qimage.bits()
    ptr.setsize(qimage.width() * qimage.height() * 4)
    img = Image.frombuffer('RGBA', (qimage.width(), qimage.height()), bytes(ptr))
    pil_images.append(img)
    print(f"  {size}x{size} OK")

pil_images[0].save(ICO_PATH, format='ICO', append_images=pil_images[1:],
                   sizes=[(s, s) for s in sizes])
print(f"\nGuardado: {ICO_PATH}")
