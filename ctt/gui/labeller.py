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
from .icons import icon
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
    """One chosen species with its count and note."""

    removed = Signal(object)

    def __init__(self, species_row, count=1, note=""):
        super().__init__()
        self.species_id = species_row["id"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        name = QLabel(f"<b>{species_row['common_name']}</b>"
                      + (f"<br><i style='color:#7A7466'>{species_row['scientific_name']}</i>"
                         if species_row["scientific_name"] else ""))
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setValue(count)
        self.count.setPrefix("× ")
        self.count.setToolTip("Number of individuals")
        self.note = QLineEdit(note)
        self.note.setPlaceholderText("note: age/sex, behaviour…")
        rm = QPushButton("×")
        rm.setFixedWidth(30)
        rm.setStyleSheet("font-size: 13pt; padding: 0 0 2px 0;")
        rm.setToolTip("Remove this species")
        rm.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(name, 3)
        lay.addWidget(self.count, 1)
        lay.addWidget(self.note, 3)
        lay.addWidget(rm)

    def value(self):
        return (self.species_id, self.count.value(), self.note.text().strip())


class SpeciesPicker(QWidget):
    """Search box + list: recently used species on top. Click to add."""

    picked = Signal(int)

    def __init__(self, con):
        super().__init__()
        self.con = con
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search species (common or scientific name)…")
        from .icons import icon as _icon

        self.search.addAction(_icon("search", "#6F7563", 18), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self._enter)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemClicked.connect(lambda it: self._pick(it))
        self.list.itemActivated.connect(lambda it: self._pick(it))
        lay.addWidget(self.list)
        self.refresh()

    def refresh(self, *_):
        q = self.search.text().strip().lower()
        sp = db.list_species(self.con, recent_first=True)
        self.list.clear()
        recent_marked = False
        for s in sp:
            hay = f"{s['common_name']} {s['scientific_name'] or ''} {s['taxon_group'] or ''}".lower()
            if q and q not in hay:
                continue
            label = s["common_name"]
            if s["scientific_name"]:
                label += f"   –  {s['scientific_name']}"
            if s["last_used_at"] and not q:
                label = "★  " + label
                recent_marked = True
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, s["id"])
            if s["taxon_group"]:
                it.setToolTip(s["taxon_group"])
            self.list.addItem(it)
        if not sp:
            it = QListWidgetItem("Species list is empty – add species via 'Species list' at the top.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
        self.list.setToolTip("★ = used recently" if recent_marked else "")

    def _enter(self):
        if self.list.count() >= 1 and self.list.item(0).data(Qt.ItemDataRole.UserRole):
            self._pick(self.list.item(0))

    def _pick(self, it):
        sid = it.data(Qt.ItemDataRole.UserRole)
        if sid:
            self.picked.emit(sid)
            self.search.clear()


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
        open_btn = QPushButton("Open / play video")
        open_btn.setIcon(icon("player-play"))
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
        right.setMinimumWidth(460)
        rl = QVBoxLayout(right)
        title = QLabel("What is in this event?")
        title.setObjectName("SectionTitle")
        rl.addWidget(title)
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
        scope.addStretch()
        rl.addLayout(scope)

        # quick labels: always one click away
        quick = QHBoxLayout()
        self.quick_buttons = {}
        for grp, text, tip, ic in (
            ("empty", "Empty", "Nothing in it (false trigger, wind, sun)", "photo-off"),
            ("human", "People / livestock", "Herders, villagers, cattle, goats, dogs…", "users"),
            ("team", "Survey team", "Your own team setting or checking the camera", "users-group"),
        ):
            b = QPushButton(text)
            b.setIcon(icon(ic, "#263A14", 18))
            b.setObjectName("Quick")
            b.setToolTip(tip + " – removed from the labelling list")
            b.clicked.connect(lambda _c=False, g=grp: self._quick(g))
            self.quick_buttons[grp] = b
            quick.addWidget(b)
        rl.addLayout(quick)

        self.override_note = QLabel()
        self.override_note.setStyleSheet("color:#b26a00")
        rl.addWidget(self.override_note)

        chosen = QLabel("Species in this event")
        chosen.setObjectName("TileNote")
        rl.addWidget(chosen)
        self.rows_box = QVBoxLayout()
        rows_w = QWidget()
        rows_w.setLayout(self.rows_box)
        self.rows_box.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rows_w)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(90)
        rl.addWidget(scroll, 2)
        pick_title = QLabel("Add a species  (★ = used recently)")
        pick_title.setObjectName("TileNote")
        rl.addWidget(pick_title)
        self.picker = SpeciesPicker(self.con)
        self.picker.picked.connect(self._picked)
        self.picker.list.setMinimumHeight(260)
        rl.addWidget(self.picker, 5)
        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("Event note"))
        self.event_note = QLineEdit()
        note_row.addWidget(self.event_note, 1)
        rl.addLayout(note_row)

        save = QPushButton("Save and go to next event")
        save.setIcon(icon("arrow-right", "#FFFFFF"))
        save.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        save.setObjectName("Primary")
        save.setMinimumHeight(38)
        save.clicked.connect(lambda: self._save(go_next=True))
        row2 = QHBoxLayout()
        prev = QPushButton("Previous")
        prev.setIcon(icon("arrow-left"))
        prev.clicked.connect(lambda: self._step(-1))
        save_only = QPushButton("Save")
        save_only.setIcon(icon("device-floppy"))
        save_only.clicked.connect(lambda: self._save(go_next=False))
        self.clear_override = QPushButton("Remove file's own labels")
        self.clear_override.clicked.connect(self._clear_override)
        for w in (prev, save_only, self.clear_override):
            row2.addWidget(w)
        rl.addWidget(save)
        rl.addLayout(row2)
        split.addWidget(right)
        split.setSizes([230, 760, 520])
        split.setStretchFactor(1, 1)

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
        self._file_labels = labels.file_labels(self.con, [self.deployment_id], a, u)
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
            names = labels.label_text(self._file_labels.get(m["id"], {}).get("labels", []))
            grp = names or GROUP_LABELS.get(m["grp"], "?")
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

    def _add_row(self, species_id, count=1, note=""):
        sp = self.con.execute("SELECT * FROM species WHERE id=?", (species_id,)).fetchone()
        if sp is None:
            return None
        row = SpeciesRow(sp, count, note)
        row.removed.connect(self._remove_row)
        self.rows_box.insertWidget(self.rows_box.count() - 1, row)
        return row

    def _picked(self, species_id):
        for r in self._rows():
            if r.species_id == species_id:  # already there: one more individual
                r.count.setValue(r.count.value() + 1)
                return
        self._add_row(species_id)

    def refresh_species(self):
        self.picker.refresh()

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

    def _save(self, go_next):
        if not self.events:
            return
        entries = [v for v in (r.value() for r in self._rows()) if v]
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
        self.picker.refresh()
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

    def select_event(self, event_id):
        if self.only_open.isChecked():
            self.only_open.setChecked(False)  # labelled events must be visible
        for i, e in enumerate(self.events):
            if e["id"] == event_id:
                self.event_list.setCurrentRow(i)
                return True
        return False

    def _quick(self, group):
        """Empty / People & livestock / Survey team for the whole event or this file."""
        if not self.events or self.event_list.currentRow() < 0:
            return
        ev = self.events[self.event_list.currentRow()]
        row = self.event_list.currentRow()
        if self.scope_file.isChecked() and self.current_media:
            labels.quick_label(self.con, [self.current_media["id"]], group)
        else:
            labels.quick_label(self.con, [m["id"] for m in self.media], group)
            labels.set_event_labels(self.con, ev["id"], [])
        self.reload()
        self.changed.emit()
        if self.event_list.count():
            self.event_list.setCurrentRow(min(row, self.event_list.count() - 1))
