"""Interactive tile map (OpenStreetMap / satellite) drawn natively in Qt.

- Drag to pan, mouse wheel to zoom, click to pick a point (in pick mode).
- Tiles are cached on disk (%APPDATA%\\CameraTrapTool\\tiles) so areas you viewed
  once while online also work in the field without internet.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QBrush
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ctt import __version__
from ctt.geo import TILE, fit_zoom, lonlat_to_pixel, pixel_to_lonlat
from . import theme

LAYERS = {
    "Street": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors",
        "max_zoom": 19,
    },
    "Satellite": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Imagery © Esri, Maxar, Earthstar Geographics",
        "max_zoom": 18,
    },
}
USER_AGENT = f"Trapster/{__version__} (Wildsolutions camera trap research desktop app)"


def cache_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "CameraTrapTool" / "tiles"


class MapCanvas(QWidget):
    clicked = Signal(float, float)        # lat, lon
    marker_clicked = Signal(object)       # marker key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 220)
        self.setMouseTracking(True)
        self.layer = "Street"
        self.zoom = 6
        self.center = (37.0, 0.0)  # lon, lat (Kenya)
        self.markers = []          # dicts: lat, lon, label, colour, radius, key
        self.pick = None           # (lat, lon) crosshair
        self.tiles = {}            # (layer, z, x, y) -> QPixmap or None (pending)
        self.net = QNetworkAccessManager(self)
        self.net.finished.connect(self._tile_loaded)
        self._drag = None
        self._moved = False
        self.offline = False

    # ---------------------------------------------------------- public
    def set_layer(self, name):
        self.layer = name
        self.zoom = min(self.zoom, LAYERS[name]["max_zoom"])
        self.update()

    def set_markers(self, markers, fit=True):
        self.markers = markers
        if fit and markers:
            self.fit([(m["lon"], m["lat"]) for m in markers])
        self.update()

    def set_pick(self, lat, lon, center=True):
        self.pick = (lat, lon) if lat is not None else None
        if center and self.pick:
            self.center = (lon, lat)
            self.zoom = max(self.zoom, 14)
        self.update()

    def fit(self, lonlats):
        if not lonlats:
            return
        self.zoom = fit_zoom(lonlats, max(self.width(), 400), max(self.height(), 300))
        xs, ys = zip(*(lonlat_to_pixel(lo, la, self.zoom) for lo, la in lonlats))
        self.center = pixel_to_lonlat((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, self.zoom)

    def zoom_by(self, d, anchor=None):
        new = max(2, min(LAYERS[self.layer]["max_zoom"], self.zoom + d))
        if new == self.zoom:
            return
        if anchor is not None:  # keep the point under the mouse fixed
            lon, lat = self._to_lonlat(anchor)
            ax, ay = anchor.x() - self.width() / 2, anchor.y() - self.height() / 2
            px, py = lonlat_to_pixel(lon, lat, new)
            self.center = pixel_to_lonlat(px - ax, py - ay, new)
        self.zoom = new
        self.update()

    # ---------------------------------------------------------- coordinates
    def _center_px(self):
        return lonlat_to_pixel(self.center[0], self.center[1], self.zoom)

    def _to_screen(self, lat, lon) -> QPointF:
        cx, cy = self._center_px()
        x, y = lonlat_to_pixel(lon, lat, self.zoom)
        return QPointF(x - cx + self.width() / 2, y - cy + self.height() / 2)

    def _to_lonlat(self, pos):
        cx, cy = self._center_px()
        return pixel_to_lonlat(cx + pos.x() - self.width() / 2, cy + pos.y() - self.height() / 2, self.zoom)

    # ---------------------------------------------------------- tiles
    def _tile(self, z, x, y):
        n = 2 ** z
        x %= n
        if y < 0 or y >= n:
            return None
        key = (self.layer, z, x, y)
        if key in self.tiles:
            return self.tiles[key]
        path = cache_dir() / self.layer / str(z) / str(x) / f"{y}.png"
        if path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                self.tiles[key] = pm
                return pm
        self.tiles[key] = None  # pending
        url = LAYERS[self.layer]["url"].format(z=z, x=x, y=y)
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", USER_AGENT.encode())
        req.setAttribute(QNetworkRequest.Attribute.User, "|".join(map(str, key)))
        self.net.get(req)
        return None

    def _tile_loaded(self, reply: QNetworkReply):
        raw = reply.request().attribute(QNetworkRequest.Attribute.User)
        if not raw:
            reply.deleteLater()
            return
        layer, z, x, y = str(raw).split("|")
        key = (layer, int(z), int(x), int(y))
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = bytes(reply.readAll())
            pm = QPixmap()
            if pm.loadFromData(data):
                self.tiles[key] = pm
                path = cache_dir() / layer / str(z) / str(x) / f"{y}.png"
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                except OSError:
                    pass
                self.offline = False
                self.update()
        else:
            self.tiles.pop(key, None)  # allow retry later
            self.offline = True
            self.update()
        reply.deleteLater()

    # ---------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#E8E4DA"))
        cx, cy = self._center_px()
        x0 = cx - self.width() / 2
        y0 = cy - self.height() / 2
        tx0, ty0 = int(math.floor(x0 / TILE)), int(math.floor(y0 / TILE))
        tx1, ty1 = int(math.floor((x0 + self.width()) / TILE)), int(math.floor((y0 + self.height()) / TILE))
        missing = 0
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                pm = self._tile(self.zoom, tx, ty)
                sx, sy = tx * TILE - x0, ty * TILE - y0
                if pm is not None:
                    p.drawPixmap(int(sx), int(sy), pm)
                else:
                    missing += 1
                    p.setPen(QPen(QColor("#D6D0C2"), 1))
                    p.drawRect(QRectF(sx, sy, TILE, TILE))

        # markers
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        for m in self.markers:
            pt = self._to_screen(m["lat"], m["lon"])
            r = m.get("radius", 7)
            col = QColor(m.get("colour", theme.OCHRE))
            col.setAlpha(m.get("alpha", 230))
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QBrush(col))
            p.drawEllipse(pt, r, r)
            if m.get("label"):
                text = m["label"]
                rect = p.fontMetrics().boundingRect(text)
                box = QRectF(pt.x() + r + 3, pt.y() - rect.height() / 2 - 2, rect.width() + 8, rect.height() + 4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 215))
                p.drawRoundedRect(box, 4, 4)
                p.setPen(QColor(theme.TEXT))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

        if self.pick:
            pt = self._to_screen(*self.pick)
            p.setPen(QPen(QColor(theme.RED), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pt, 9, 9)
            p.drawLine(QPointF(pt.x() - 16, pt.y()), QPointF(pt.x() - 5, pt.y()))
            p.drawLine(QPointF(pt.x() + 5, pt.y()), QPointF(pt.x() + 16, pt.y()))
            p.drawLine(QPointF(pt.x(), pt.y() - 16), QPointF(pt.x(), pt.y() - 5))
            p.drawLine(QPointF(pt.x(), pt.y() + 5), QPointF(pt.x(), pt.y() + 16))

        # attribution + scale bar
        f.setBold(False)
        f.setPointSizeF(7.5)
        p.setFont(f)
        attr = LAYERS[self.layer]["attribution"]
        if self.offline and missing:
            attr = "Offline – showing saved map tiles only.  " + attr
        w = p.fontMetrics().horizontalAdvance(attr) + 10
        r = QRectF(self.width() - w, self.height() - 16, w, 16)
        p.fillRect(r, QColor(255, 255, 255, 200))
        p.setPen(QColor("#555"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, attr)
        self._scale_bar(p)
        p.end()

    def _scale_bar(self, p):
        lat = self.center[1]
        m_per_px = 156543.03392 * math.cos(math.radians(lat)) / (2 ** self.zoom)
        target = m_per_px * 100
        nice = 10 ** math.floor(math.log10(target))
        for k in (5, 2, 1):
            if k * nice <= target:
                nice *= k
                break
        px = nice / m_per_px
        x, y = 12, self.height() - 14
        p.fillRect(QRectF(x - 4, y - 16, px + 8, 22), QColor(255, 255, 255, 200))
        p.setPen(QPen(QColor(theme.TEXT), 2))
        p.drawLine(QPointF(x, y), QPointF(x + px, y))
        p.drawLine(QPointF(x, y - 4), QPointF(x, y))
        p.drawLine(QPointF(x + px, y - 4), QPointF(x + px, y))
        label = f"{nice / 1000:g} km" if nice >= 1000 else f"{nice:g} m"
        p.drawText(QRectF(x, y - 16, px, 12), Qt.AlignmentFlag.AlignCenter, label)

    # ---------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = (e.position(), self._center_px())
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag:
            start, (cx, cy) = self._drag
            d = e.position() - start
            if abs(d.x()) + abs(d.y()) > 3:
                self._moved = True
            self.center = pixel_to_lonlat(cx - d.x(), cy - d.y(), self.zoom)
            self.update()
        else:
            hit = self._marker_at(e.position())
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.OpenHandCursor)
            self.setToolTip(hit.get("tooltip", hit.get("label", "")) if hit else "")

    def mouseReleaseEvent(self, e):
        if self._drag and not self._moved and e.button() == Qt.MouseButton.LeftButton:
            hit = self._marker_at(e.position())
            if hit is not None and hit.get("key") is not None:
                self.marker_clicked.emit(hit["key"])
            else:
                lon, lat = self._to_lonlat(e.position())
                self.clicked.emit(lat, lon)
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.zoom_by(1, e.position())

    def wheelEvent(self, e):
        self.zoom_by(1 if e.angleDelta().y() > 0 else -1, e.position())

    def _marker_at(self, pos):
        for m in reversed(self.markers):
            pt = self._to_screen(m["lat"], m["lon"])
            if (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= (m.get("radius", 7) + 3) ** 2:
                return m
        return None


class MapWidget(QWidget):
    """Map canvas with Street/Satellite switch and zoom buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self.canvas = MapCanvas()
        group = QButtonGroup(self)
        for name in LAYERS:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(name == "Street")
            b.clicked.connect(lambda _c, n=name: self.canvas.set_layer(n))
            group.addButton(b)
            bar.addWidget(b)
        bar.addStretch()
        self.hint = QLabel("Drag to move · scroll to zoom")
        self.hint.setObjectName("TileNote")
        bar.addWidget(self.hint)
        for txt, d in (("+", 1), ("−", -1)):
            b = QPushButton(txt)
            b.setFixedWidth(34)
            b.clicked.connect(lambda _c, d=d: self.canvas.zoom_by(d))
            bar.addWidget(b)
        fit = QPushButton("Fit")
        fit.clicked.connect(self._fit)
        bar.addWidget(fit)
        lay.addLayout(bar)
        lay.addWidget(self.canvas, 1)

    def _fit(self):
        pts = [(m["lon"], m["lat"]) for m in self.canvas.markers]
        if self.canvas.pick:
            pts.append((self.canvas.pick[1], self.canvas.pick[0]))
        self.canvas.fit(pts)
        self.canvas.update()
