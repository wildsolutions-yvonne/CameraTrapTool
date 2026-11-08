"""Home page: all projects as photo cards."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from . import theme
from .assets import asset_path

CARD_W, PHOTO_H = 300, 170


def project_counts(con, pid) -> dict:
    r = con.execute(
        """SELECT
             (SELECT COUNT(*) FROM station WHERE project_id=:p) stations,
             (SELECT COUNT(*) FROM deployment d JOIN station s ON s.id=d.station_id WHERE s.project_id=:p) deployments,
             (SELECT COUNT(*) FROM media m JOIN deployment d ON d.id=m.deployment_id
                JOIN station s ON s.id=d.station_id WHERE s.project_id=:p) files,
             (SELECT COUNT(DISTINCT l.species_id) FROM label l JOIN event e ON e.id=l.event_id
                JOIN deployment d ON d.id=e.deployment_id JOIN station s ON s.id=d.station_id
                WHERE s.project_id=:p) species""",
        {"p": pid},
    ).fetchone()
    return dict(r)


def cover_pixmap(photo_path, name, w=CARD_W, h=PHOTO_H) -> QPixmap:
    """Project photo cropped to fill w x h, or a coloured placeholder with initials."""
    pm = QPixmap(w, h)
    pm.fill(QColor(theme.OLIVE))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    src = QPixmap(photo_path) if photo_path and Path(photo_path).exists() else QPixmap()
    if not src.isNull():
        s = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(0, 0, s, (s.width() - w) // 2, (s.height() - h) // 2, w, h)
    else:
        # placeholder: soft stripes + initials
        for i in range(0, w + h, 26):
            p.setPen(QColor(255, 255, 255, 18))
            p.drawLine(i, 0, i - h, h)
        initials = "".join(x[0] for x in name.split()[:2]).upper() or "?"
        f = QFont()
        f.setPointSize(30)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, initials)
    p.end()
    # rounded top corners
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h + 12), 10, 10)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


class ProjectCard(QFrame):
    opened = Signal(int)
    edit = Signal(int)
    delete = Signal(int)

    def __init__(self, project, counts):
        super().__init__()
        self.pid = project["id"]
        self.setObjectName("Card")
        self.setProperty("clickable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(CARD_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(4)
        photo = QLabel()
        photo.setPixmap(cover_pixmap(project["photo_path"], project["name"]))
        lay.addWidget(photo)
        body = QVBoxLayout()
        body.setContentsMargins(14, 6, 14, 0)
        top = QHBoxLayout()
        name = QLabel(project["name"])
        name.setStyleSheet(f"font-size: 13pt; font-weight: 600; color: {theme.OLIVE_DARK};")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        more = QPushButton("⋯")
        more.setObjectName("Flat")
        more.setFixedWidth(30)
        more.setStyleSheet("text-decoration: none; font-size: 14pt;")
        more.clicked.connect(self._menu)
        top.addWidget(more)
        body.addLayout(top)
        if project["location"]:
            loc = QLabel("📍 " + project["location"])
            loc.setObjectName("PageSubtitle")
            body.addWidget(loc)
        stats = QLabel(
            f"<b>{counts['stations']}</b> stations · <b>{counts['deployments']}</b> deployments<br>"
            f"<b>{counts['files']:,}</b> files · <b>{counts['species']}</b> species"
        )
        stats.setObjectName("PageSubtitle")
        body.addWidget(stats)
        lay.addLayout(body)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.opened.emit(self.pid)

    def contextMenuEvent(self, e):
        self._menu()

    def _menu(self):
        m = QMenu(self)
        m.addAction("Open", lambda: self.opened.emit(self.pid))
        m.addAction("Edit name, photo…", lambda: self.edit.emit(self.pid))
        m.addSeparator()
        m.addAction("Delete project…", lambda: self.delete.emit(self.pid))
        m.exec(self.cursor().pos())


class NewProjectCard(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self.setProperty("clickable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(CARD_W, PHOTO_H + 100)
        lay = QVBoxLayout(self)
        plus = QLabel("+")
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet(f"font-size: 44pt; color: {theme.OCHRE}; font-weight: 300;")
        t = QLabel("New project")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {theme.OLIVE_DARK};")
        lay.addStretch()
        lay.addWidget(plus)
        lay.addWidget(t)
        lay.addStretch()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class HomePage(QWidget):
    open_project = Signal(int)
    new_project = Signal()
    edit_project = Signal(int)
    delete_project = Signal(int)

    def __init__(self, con):
        super().__init__()
        self.con = con
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(40, 30, 40, 30)

        hero = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(asset_path("logo_256.png"))).scaled(
            84, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        hero.addWidget(logo)
        txt = QVBoxLayout()
        t = QLabel("Your projects")
        t.setObjectName("PageTitle")
        sub = QLabel("Find the empty camera trap files, label what's left, and see the results per station.")
        sub.setObjectName("PageSubtitle")
        txt.setSpacing(2)
        txt.addWidget(t)
        txt.addWidget(sub)
        hero.addLayout(txt, 1)
        newb = QPushButton("+  New project")
        newb.setObjectName("Primary")
        newb.clicked.connect(self.new_project)
        hero.addWidget(newb, 0, Qt.AlignmentFlag.AlignVCenter)
        self.lay.addLayout(hero)
        self.lay.addSpacing(24)

        self.grid_host = QWidget()
        self.grid_host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(22)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lay.addWidget(self.grid_host)
        self.lay.addStretch(100)
        self._cols = 0

    def reload(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        projects = self.con.execute("SELECT * FROM project ORDER BY created_at DESC, name").fetchall()
        self.cards = []
        for p in projects:
            c = ProjectCard(p, project_counts(self.con, p["id"]))
            c.opened.connect(self.open_project)
            c.edit.connect(self.edit_project)
            c.delete.connect(self.delete_project)
            self.cards.append(c)
        nc = NewProjectCard()
        nc.clicked.connect(self.new_project)
        self.cards.append(nc)
        self._layout_cards(force=True)

    def _layout_cards(self, force=False):
        cols = max(1, (self.width() - 80) // (CARD_W + 22))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols, Qt.AlignmentFlag.AlignTop)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "cards", None):
            self._layout_cards()
