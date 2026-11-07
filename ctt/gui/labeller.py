"""Manual labelling of events (bursts) with species, counts and notes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QCompleter, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from ctt import db, labels
from ctt.grouping import EMPTY, GROUP_LABELS
from ctt.processing import corrected_time
from .util import load_image, open_file
from .workers import ThumbnailWorker


class ImageView(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet("background:#222; color:#ccc")
        self._pix = None

    def set_image(self, img):
        self._pix = None if img is None or img.isNull() else QPixmap.fromImage(img)
        if self._pix is None:
            self.setText("Could not show this file")
        self._rescale()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._pix:
            self.setPixmap(self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))


class SpeciesRow(QWidget):
    removed = Signal(object)

    def __init__(self, species, species_id=None, count=1, note=""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.addItem("— choose species —", None)
        for s in species:
            self.combo.addItem(s["common_name"], s["id"])
        comp = self.combo.completer()
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        if species_id:
            self.combo.setCurrentIndex(max(0, self.combo.findData(species_id)))
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setValue(count)
        self.count.setPrefix("× ")
        self.note = QLineEdit(note)
        self.note.setPlaceholderText("note (age/sex, behaviour…)")
        rm = QPushButton("✖")
        rm.setFixedWidth(28)
        rm.setToolTip("Remove this species")
        rm.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(self.combo, 3)
        lay.addWidget(self.count, 1)
        lay.addWidget(self.note, 3)
        lay.addWidget(rm)

    def value(self):
        idx = self.combo.findText(self.combo.currentText(), Qt.MatchFlag.MatchFixedString)
        sid = self.combo.itemData(idx) if idx >= 0 else None
        return (sid, self.count.value(), self.note.text().strip()) if sid else None


class Labeller(QWidget):
    changed = Signal()

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.deployment_id = None
        self.events = []
        self.media = []
        self.current_media = None
        self.thumb_worker = None

        split = QSplitter(Qt.Orientation.Horizontal)
        QVBoxLayout(self).addWidget(split)

        # --- left: events
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Events</b> (photos close in time)"))
        self.only_open = QCheckBox("Only show events not yet labelled")
        self.only_open.toggled.connect(lambda: self.reload(keep=True))
        ll.addWidget(self.only_open)
        self.event_list = QListWidget()
        self.event_list.currentRowChanged.connect(self._select_event)
        ll.addWidget(self.event_list)
        self.progress = QLabel()
        ll.addWidget(self.progress)
        split.addWidget(left)

        # --- centre: image + strip
        mid = QWidget()
        ml = QVBoxLayout(mid)
        self.view = ImageView()
        ml.addWidget(self.view, 1)
        info = QHBoxLayout()
        self.file_info = QLabel()
        self.file_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = QPushButton("Open in viewer / play video")
        open_btn.clicked.connect(self._open_current)
        info.addWidget(self.file_info, 1)
        info.addWidget(open_btn)
        ml.addLayout(info)
        self.strip = QListWidget()
        self.strip.setViewMode(QListWidget.ViewMode.IconMode)
        self.strip.setFlow(QListWidget.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setIconSize(QSize(120, 90))
        self.strip.setFixedHeight(130)
        self.strip.setMovement(QListWidget.Movement.Static)
        self.strip.currentRowChanged.connect(self._select_file)
        ml.addWidget(self.strip)
        split.addWidget(mid)

        # --- right: labels
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("<b>What is in this event?</b>"))
        scope = QHBoxLayout()
        self.scope_event = QRadioButton("Whole event")
        self.scope_file = QRadioButton("This file only")
        self.scope_event.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.scope_event)
        bg.addButton(self.scope_file)
        self.scope_event.toggled.connect(self._load_label_rows)
        scope.addWidget(self.scope_event)
        scope.addWidget(self.scope_file)
        rl.addLayout(scope)
        self.override_note = QLabel()
        self.override_note.setStyleSheet("color:#b26a00")
        rl.addWidget(self.override_note)

        self.rows_box = QVBoxLayout()
        rows_w = QWidget()
        rows_w.setLayout(self.rows_box)
        self.rows_box.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rows_w)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        rl.addWidget(scroll, 1)
        add = QPushButton("+ Add species")
        add.clicked.connect(lambda: self._add_row())
        rl.addWidget(add)
        rl.addWidget(QLabel("Event note"))
        self.event_note = QLineEdit()
        rl.addWidget(self.event_note)

        save = QPushButton("Save and go to next event  ▶")
        save.setStyleSheet("font-weight:bold; padding:8px")
        save.clicked.connect(lambda: self._save(go_next=True))
        save_only = QPushButton("Save")
        save_only.clicked.connect(lambda: self._save(go_next=False))
        self.clear_override = QPushButton("Remove this file's own labels")
        self.clear_override.clicked.connect(self._clear_override)
        empty = QPushButton("Nothing here — mark whole event as empty")
        empty.clicked.connect(self._mark_empty)
        prev = QPushButton("◀ Previous event")
        prev.clicked.connect(lambda: self._step(-1))
        for b in (save, save_only, self.clear_override, empty, prev):
            rl.addWidget(b)
        split.addWidget(right)
        split.setSizes([260, 800, 420])

    # ------------------------------------------------------------ data
    def load(self, deployment_id):
        self.deployment_id = deployment_id
        self.reload()

    def _thresholds(self):
        dep = db.get_deployment(self.con, self.deployment_id)
        p = db.get_project(self.con, dep["project_id"])
        return dep, p["animal_threshold"], p["uncertain_threshold"]

    def reload(self, keep=False):
        if self.deployment_id is None:
            return
        cur_id = self.events[self.event_list.currentRow()]["id"] if keep and self.event_list.currentRow() >= 0 and self.events else None
        self.dep, a, u = self._thresholds()
        evs = labels.events_to_label(self.con, self.deployment_id, a, u)
        done = sum(1 for e in evs if e["n_labels"])
        self.progress.setText(f"{done} of {len(evs)} events labelled")
        if self.only_open.isChecked():
            evs = [e for e in evs if not e["n_labels"]]
        self.events = evs
        self.event_list.blockSignals(True)
        self.event_list.clear()
        sel = 0
        for i, e in enumerate(evs):
            ts = corrected_time(e["start_at"], self.dep["time_offset_seconds"])
            when = f"{ts:%Y-%m-%d %H:%M}" if ts else "no time"
            names = ", ".join(f"{l['common_name']} ×{l['count']}" for l in labels.event_labels(self.con, e["id"]))
            mark = "✔" if e["n_labels"] else "○"
            self.event_list.addItem(f"{mark} {when} · {e['n_files']} file(s)" + (f"\n    {names}" if names else ""))
            if e["id"] == cur_id:
                sel = i
        self.event_list.blockSignals(False)
        if evs:
            self.event_list.setCurrentRow(sel)
        else:
            self.strip.clear()
            self.view.set_image(None)
            self.view.setText("No events to label. Process the deployment first, or all events are done.")

    def _select_event(self, row):
        if row < 0 or row >= len(self.events):
            return
        ev = self.events[row]
        _, a, u = self._thresholds()
        self.media = labels.event_media(self.con, ev["id"], a, u)
        self.event_note.setText(ev["note"] or "")
        folder = Path(self.dep["folder"])
        if self.thumb_worker:
            self.thumb_worker.stop()
            self.thumb_worker.wait()
        self.strip.blockSignals(True)
        self.strip.clear()
        ph = QPixmap(120, 90)
        ph.fill(QColor("#ccc"))
        items = []
        first_interesting = 0
        for i, m in enumerate(self.media):
            grp = GROUP_LABELS.get(m["grp"], "?")
            it = QListWidgetItem(QIcon(ph), ("▶ " if m["kind"] == "video" else "") + grp)
            self.strip.addItem(it)
            items.append((i, str(folder / m["relpath"]), m["kind"], m["best_frame_seconds"]))
            if m["grp"] in ("animal", "human") and first_interesting == 0 and self.media[0]["grp"] not in ("animal", "human"):
                first_interesting = i
        self.strip.blockSignals(False)
        self.thumb_worker = ThumbnailWorker(items, 160)
        self.thumb_worker.ready.connect(self._strip_thumb)
        self.thumb_worker.start()
        self.scope_event.setChecked(True)
        self.strip.setCurrentRow(first_interesting)

    def _strip_thumb(self, i, img):
        it = self.strip.item(i)
        if it and not img.isNull():
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def _select_file(self, row):
        if row < 0 or row >= len(self.media):
            return
        m = self.media[row]
        self.current_media = m
        path = Path(self.dep["folder"]) / m["relpath"]
        self.view.set_image(load_image(path, m["kind"], m["best_frame_seconds"], 2000))
        ts = corrected_time(m["taken_at"], self.dep["time_offset_seconds"])
        self.file_info.setText(
            f"{m['relpath']}   |   {ts:%Y-%m-%d %H:%M:%S}   |   detector: animal {m['max_animal'] or 0:.2f}"
            if ts else m["relpath"]
        )
        self._load_label_rows()

    def _open_current(self):
        if self.current_media:
            open_file(Path(self.dep["folder"]) / self.current_media["relpath"])

    # ------------------------------------------------------------ label rows
    def _clear_rows(self):
        while self.rows_box.count() > 1:
            w = self.rows_box.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _add_row(self, species_id=None, count=1, note=""):
        row = SpeciesRow(db.list_species(self.con), species_id, count, note)
        row.removed.connect(self._remove_row)
        self.rows_box.insertWidget(self.rows_box.count() - 1, row)
        return row

    def _remove_row(self, row):
        self.rows_box.removeWidget(row)
        row.deleteLater()

    def _rows(self):
        out = []
        for i in range(self.rows_box.count() - 1):
            w = self.rows_box.itemAt(i).widget()
            if isinstance(w, SpeciesRow):
                out.append(w)
        return out

    def _load_label_rows(self, *_):
        self._clear_rows()
        if not self.events or self.event_list.currentRow() < 0:
            return
        ev = self.events[self.event_list.currentRow()]
        own = labels.media_labels(self.con, self.current_media["id"]) if self.current_media else []
        self.override_note.setText("This file has its own labels (different from the event)." if own else "")
        self.clear_override.setEnabled(bool(own))
        current = own if self.scope_file.isChecked() else labels.event_labels(self.con, ev["id"])
        for l in current:
            self._add_row(l["species_id"], l["count"], l["note"])
        if not current:
            self._add_row()

    def _save(self, go_next):
        if not self.events:
            return
        entries = [v for v in (r.value() for r in self._rows()) if v]
        unknown = [r.combo.currentText() for r in self._rows() if not r.value() and r.combo.currentIndex() != 0
                   and r.combo.currentText().strip() and r.combo.currentText() != "— choose species —"]
        if unknown:
            QMessageBox.warning(self, "Unknown species",
                                "Not in the species list: " + ", ".join(unknown) +
                                "\nAdd it via Settings → Species list, or pick from the list.")
            return
        ev = self.events[self.event_list.currentRow()]
        if self.scope_file.isChecked():
            if self.current_media:
                labels.set_media_labels(self.con, self.current_media["id"], entries)
        else:
            if not entries and not QMessageBox.question(
                self, "No species", "Save this event without any species?"
            ) == QMessageBox.StandardButton.Yes:
                return
            labels.set_event_labels(self.con, ev["id"], entries, note=self.event_note.text())
        row = self.event_list.currentRow()
        self.reload(keep=True)
        self.changed.emit()
        if go_next:
            self._step(1, from_row=row)

    def _step(self, d, from_row=None):
        row = (self.event_list.currentRow() if from_row is None else from_row) + d
        if self.only_open.isChecked() and d > 0:
            row = from_row if from_row is not None else self.event_list.currentRow()
        if 0 <= row < self.event_list.count():
            self.event_list.setCurrentRow(row)

    def _clear_override(self):
        if self.current_media:
            labels.set_media_labels(self.con, self.current_media["id"], [])
            self._load_label_rows()
            self.changed.emit()

    def _mark_empty(self):
        if not self.events:
            return
        ev = self.events[self.event_list.currentRow()]
        labels.set_manual_group(self.con, [m["id"] for m in self.media], EMPTY)
        labels.set_event_labels(self.con, ev["id"], [])
        row = self.event_list.currentRow()
        self.reload()
        self.changed.emit()
        if self.event_list.count():
            self.event_list.setCurrentRow(min(row, self.event_list.count() - 1))
