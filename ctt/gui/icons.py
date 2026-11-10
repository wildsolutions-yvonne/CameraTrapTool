"""Line icons (Tabler Icons, MIT licence) coloured to match the theme."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .assets import asset_path


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#263A14", size: int = 20, stroke: float = 2.0) -> QPixmap:
    path = asset_path(f"icons/{name}.svg")
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:
        return QPixmap()
    svg = svg.replace('stroke="currentColor"', f'stroke="{color}"').replace('stroke-width="2"', f'stroke-width="{stroke}"')
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = 2  # sharp on high-DPI screens
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str = "#263A14", size: int = 20) -> QIcon:
    ic = QIcon(pixmap(name, color, size))
    ic.addPixmap(pixmap(name, "#B4AEA0", size), QIcon.Mode.Disabled)
    return ic
