"""Neonowe ikony HUD: wczytaj SVG → podmień `currentColor` na kolor akcentu →
renderuj przez QSvgRenderer do QPixmap. QtSvg nie rozwiązuje `currentColor`, więc
recolor robimy string-replace'em. Wyniki cache'owane.

Zwracana QPixmap jest WSPÓŁDZIELONA (cache) — tylko do wyświetlania (QLabel.setPixmap /
QPushButton.setIcon kopiują zawartość); nie rysować po niej QPainterem poza tą funkcją."""
from functools import lru_cache
from pathlib import Path

from PySide6 import QtCore, QtGui
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR = Path(__file__).parent / "icons"
ICON_NAMES = [
    "cpu", "gpu", "ram", "swap", "net-rx", "net-tx",
    "disk-read", "disk-write", "thermal", "processes", "live",
    "system", "motherboard",
]


@lru_cache(maxsize=128)
def recolored_svg(name: str, color: str) -> str:
    """Treść SVG z `currentColor` zamienionym na `color`. FileNotFoundError dla złej nazwy."""
    return (ICONS_DIR / f"{name}.svg").read_text().replace("currentColor", color)


@lru_cache(maxsize=256)
def neon_pixmap(name: str, color: str, px: int = 18) -> QtGui.QPixmap:
    renderer = QSvgRenderer(QtCore.QByteArray(recolored_svg(name, color).encode()))
    pm = QtGui.QPixmap(px, px)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    renderer.render(p)
    p.end()
    return pm
