"""Thumbnail grid to double-check Empty (or Uncertain / Human) files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from ctt import db, labels
from ctt.grouping import ANIMAL, EMPTY, HUMAN, UNCERTAIN, GROUP_LABELS
from .util import open_file
from .workers import ThumbnailWorker

PAGE = 120
THUMB = 220


class ReviewGrid(QWidget):
    changed = Signal()

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.deployment_id = None
        self.rows = []
        self.page = 0
        self.worker = None

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show:"))
        self.group = QComboBox()
        for g in (EMPTY, UNCERTAIN, HUMAN, ANIMAL):
            self.group.addItem(GROUP_LABELS[g], g)
        self.group.currentIndexChanged.connect(lambda: self.reload(reset_page=True))
        top.addWidget(self.group)
        top.addStretch()
        self.prev = QPushButton("◀ Previous page")
        self.next = QPushButton("Next page ▶")
        self.page_label = QLabel()
        self.prev.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        top.addWidget(self.prev)
        top.addWidget(self.page_label)
        top.addWidget(self.next)
        lay.addLayout(top)

        lay.addWidget(QLabel(
            "Click files to select them (Ctrl/Shift for several), then use the buttons below. "
            "Double-click opens the file in its normal viewer/player."
        ))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB * 3 // 4))
        self.list.setGridSize(QSize(THUMB + 16, THUMB * 3 // 4 + 40))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.list)

        btns = QHBoxLayout()
        self.b_animal = QPushButton("✔ Has an animal")
        self.b_human = QPushButton("Human / vehicle")
        self.b_empty = QPushButton("✖ Really empty")
        self.b_reset = QPushButton("Undo (use detector result)")
        self.b_animal.clicked.connect(lambda: self._mark(ANIMAL))
        self.b_human.clicked.connect(lambda: self._mark(HUMAN))
        self.b_empty.clicked.connect(lambda: self._mark(EMPTY))
        self.b_reset.clicked.connect(lambda: self._mark(None))
        for b in (self.b_animal, self.b_human, self.b_empty, self.b_reset):
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)

    def load(self, deployment_id, group=None):
        self.deployment_id = deployment_id
        if group:
            idx = self.group.findData(group)
            self.group.blockSignals(True)
            self.group.setCurrentIndex(idx)
            self.group.blockSignals(False)
        self.reload(reset_page=True)

    def reload(self, reset_page=False):
        if self.deployment_id is None:
            return
        dep = db.get_deployment(self.con, self.deployment_id)
        proj = db.get_project(self.con, dep["project_id"])
        self.folder = Path(dep["folder"])
        self.rows = labels.media_in_group(
            self.con, self.deployment_id, self.group.currentData(),
            proj["animal_threshold"], proj["uncertain_threshold"],
        )
        if reset_page:
            self.page = 0
        self.page = min(self.page, max(0, (len(self.rows) - 1) // PAGE))
        self._show_page()

    def _go(self, d):
        self.page += d
        self._show_page()

    def _show_page(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self.list.clear()
        n_pages = max(1, (len(self.rows) + PAGE - 1) // PAGE)
        self.page_label.setText(f"Page {self.page + 1} of {n_pages}  ({len(self.rows)} files)")
        self.prev.setEnabled(self.page > 0)
        self.next.setEnabled(self.page < n_pages - 1)
        chunk = self.rows[self.page * PAGE : (self.page + 1) * PAGE]
        placeholder = QPixmap(THUMB, THUMB * 3 // 4)
        placeholder.fill(QColor("#ddd"))
        items = []
        for i, r in enumerate(chunk):
            score = max(r["max_animal"] or 0, r["max_person"] or 0, r["max_vehicle"] or 0)
            text = f"{Path(r['relpath']).name}\nscore {score:.2f}" + (" • edited" if r["manual_group"] else "")
            it = QListWidgetItem(QIcon(placeholder), text)
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            it.setData(Qt.ItemDataRole.UserRole + 1, str(self.folder / r["relpath"]))
            if r["kind"] == "video":
                it.setText("▶ " + text)
            self.list.addItem(it)
            items.append((i, str(self.folder / r["relpath"]), r["kind"], r["best_frame_seconds"]))
        self.worker = ThumbnailWorker(items, THUMB)
        self.worker.ready.connect(self._thumb)
        self.worker.start()

    def _thumb(self, i, img):
        it = self.list.item(i)
        if it is not None and not img.isNull():
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def _open(self, item):
        open_file(item.data(Qt.ItemDataRole.UserRole + 1))

    def _mark(self, group):
        ids = [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]
        if not ids:
            return
        labels.set_manual_group(self.con, ids, group)
        self.reload()
        self.changed.emit()
