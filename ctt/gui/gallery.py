"""All footage of one species (or taxon group) in a project, as a thumbnail gallery."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from ctt.footage import species_footage
from .util import open_file
from .workers import ThumbnailWorker

PAGE = 120
THUMB = 240


class FootageGallery(QDialog):
    go_to_event = Signal(int, int)   # deployment id, event id

    def __init__(self, parent, con, project_id, title, names: set):
        super().__init__(parent)
        self.setWindowTitle(f"Footage – {title}")
        self.resize(1250, 820)
        self.rows = species_footage(con, project_id, names)
        self.page = 0
        self.worker = None
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("PageTitle")
        head.addWidget(t)
        n_videos = sum(1 for r in self.rows if r["media"]["kind"] == "video")
        sub = QLabel(f"{len(self.rows):,} files  ·  {n_videos:,} videos  ·  "
                     f"{len({r['station'] for r in self.rows})} station(s)")
        sub.setObjectName("PageSubtitle")
        head.addWidget(sub)
        head.addStretch()
        head.addWidget(QLabel("Station:"))
        self.station = QComboBox()
        self.station.addItem("All stations", None)
        for s in sorted({r["station"] for r in self.rows}):
            self.station.addItem(s, s)
        self.station.currentIndexChanged.connect(lambda: self._show(reset=True))
        head.addWidget(self.station)
        lay.addLayout(head)
        hint = QLabel("Double-click to open the photo or play the video. Select one and click "
                      "'Show in labelling' to change its label.")
        hint.setObjectName("TileNote")
        lay.addWidget(hint)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB * 3 // 4))
        self.list.setGridSize(QSize(THUMB + 18, THUMB * 3 // 4 + 58))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda it: open_file(it.data(Qt.ItemDataRole.UserRole + 1)))
        lay.addWidget(self.list, 1)
        foot = QHBoxLayout()
        self.prev = QPushButton("◀ Previous page")
        self.next = QPushButton("Next page ▶")
        self.page_label = QLabel()
        self.prev.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        goto = QPushButton("Show in labelling")
        goto.setObjectName("Primary")
        goto.clicked.connect(self._goto)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for w in (self.prev, self.page_label, self.next):
            foot.addWidget(w)
        foot.addStretch()
        foot.addWidget(goto)
        foot.addWidget(close)
        lay.addLayout(foot)
        self._show(reset=True)

    def _filtered(self):
        st = self.station.currentData()
        return [r for r in self.rows if st is None or r["station"] == st]

    def _go(self, d):
        self.page += d
        self._show()

    def _show(self, reset=False):
        if reset:
            self.page = 0
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        rows = self._filtered()
        n_pages = max(1, (len(rows) + PAGE - 1) // PAGE)
        self.page = min(self.page, n_pages - 1)
        self.page_label.setText(f"Page {self.page + 1} of {n_pages}")
        self.prev.setEnabled(self.page > 0)
        self.next.setEnabled(self.page < n_pages - 1)
        self.list.clear()
        ph = QPixmap(THUMB, THUMB * 3 // 4)
        ph.fill(QColor("#ddd"))
        items = []
        for i, r in enumerate(rows[self.page * PAGE:(self.page + 1) * PAGE]):
            m = r["media"]
            path = str(Path(r["folder"]) / m["relpath"])
            when = f"{r['when']:%Y-%m-%d %H:%M}" if r["when"] else ""
            text = ("▶ " if m["kind"] == "video" else "") + f"{r['labels']}\n{r['station']} · {when}"
            it = QListWidgetItem(QIcon(ph), text)
            it.setData(Qt.ItemDataRole.UserRole, (m["deployment_id"], m["event_id"]))
            it.setData(Qt.ItemDataRole.UserRole + 1, path)
            it.setToolTip(path)
            self.list.addItem(it)
            items.append((i, path, m["kind"], m["best_frame_seconds"]))
        self.worker = ThumbnailWorker(items, THUMB)
        self.worker.ready.connect(self._thumb)
        self.worker.start()

    def _thumb(self, i, img):
        it = self.list.item(i)
        if it is not None and not img.isNull():
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def _goto(self):
        it = self.list.currentItem()
        if it:
            dep, ev = it.data(Qt.ItemDataRole.UserRole)
            self.go_to_event.emit(int(dep), int(ev or 0))
            self.accept()

    def done(self, r):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        super().done(r)
