"""Generate decorative assets (grit texture + stencil wordmark) from the key-art
palette, using Qt (no Pillow dependency). Re-run to regenerate:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python tools/gen_assets.py

Outputs (committed PNGs):
  assets/textures/grit.png   — tiling warm concrete/grit window background
  assets/wordmark.png        — "KICKFLIP SHUFFLE" stencil wordmark (transparent)
"""
import random
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (QImage, QPainter, QColor, QFontDatabase, QFont,
                           QPen)
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
INK = "#0d0b07"
PANEL = "#16130d"
AMBER = "#e2b84a"
RED = "#c42b1e"


def make_grit(path, size=256, seed=7):
    """A subtly noisy warm-dark tile: base panel colour + per-pixel grain +
    a few faint scratches. Tiles acceptably as a window background."""
    rng = random.Random(seed)
    img = QImage(size, size, QImage.Format_ARGB32)
    base = QColor(PANEL)
    img.fill(base)
    for _ in range(size * size // 5):           # speckle grain
        x, y = rng.randrange(size), rng.randrange(size)
        d = rng.randint(-16, 16)
        img.setPixelColor(x, y, QColor(
            max(0, min(255, base.red() + d)),
            max(0, min(255, base.green() + d)),
            max(0, min(255, base.blue() + d))))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for _ in range(14):                          # faint scratches
        pen = QPen(QColor(232, 226, 210, rng.randint(6, 18)))
        pen.setWidthF(rng.uniform(0.4, 1.2))
        p.setPen(pen)
        x1, y1 = rng.randrange(size), rng.randrange(size)
        p.drawLine(x1, y1, x1 + rng.randint(-60, 60), y1 + rng.randint(-8, 8))
    p.end()
    img.save(str(path))
    return path


def make_wordmark(path, text="KICKFLIP SHUFFLE"):
    """Stencil wordmark in Saira Stencil One (amber with a red misregister ghost)
    on transparency."""
    fid = QFontDatabase.addApplicationFont(
        str(ASSETS / "fonts" / "SairaStencilOne-Regular.ttf"))
    fams = QFontDatabase.applicationFontFamilies(fid)
    family = fams[0] if fams else "Impact"
    font = QFont(family, 64)

    w, h = 1100, 170
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setFont(font)
    rect = QRectF(0, 0, w, h)
    p.setPen(QColor(RED))                        # misregister ghost, offset
    p.drawText(rect.adjusted(7, 6, 7, 6), Qt.AlignCenter, text)
    p.setPen(QColor(AMBER))                      # main fill
    p.drawText(rect, Qt.AlignCenter, text)
    p.end()
    img.save(str(path))
    return path


def main():
    app = QApplication.instance() or QApplication([])
    (ASSETS / "textures").mkdir(parents=True, exist_ok=True)
    g = make_grit(ASSETS / "textures" / "grit.png")
    w = make_wordmark(ASSETS / "wordmark.png")
    print("wrote", g)
    print("wrote", w)


if __name__ == "__main__":
    main()
