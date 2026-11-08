"""One deployment: process it, check empty files, label animals, sort copies, fix time."""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ctt import db, labels, processing, sorting
from ctt.grouping import GROUP_LABELS
from . import theme
from .dashboard import Tile
from .dialogs import TimeCorrectionDialog
from .labeller import Labeller
from .review_grid import ReviewGrid
from .util import open_file
from .workers import ProcessWorker, SortWorker


def fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class ProgressTracker:
    """Percentage, speed and time remaining (moving average over the last 30 files)."""

    def __init__(self):
        self.times = deque(maxlen=30)
        self.start = time.monotonic()

    def update(self, done, total):
        now = time.monotonic()
        self.times.append((now, done))
        pct = 100 * done / total if total else 100
        if len(self.times) >= 3:
            (t0, d0), (t1, d1) = self.times[0], self.times[-1]
            rate = (d1 - d0) / (t1 - t0) if t1 > t0 else 0
        else:
            rate = 0
        eta = (total - done) / rate if rate > 0 else None
        return pct, rate, eta, now - self.start


class DeploymentPage(QWidget):
    changed = Signal()

    def __init__(self, con, db_path):
        super().__init__()
        self.con = con
        self.db_path = db_path
        self.deployment_id = None
        self.worker = None
        self.sort_worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        tl = QVBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.info = QLabel()
        self.info.setObjectName("PageSubtitle")
        self.info.setWordWrap(True)
        tl.addWidget(self.title)
        tl.addWidget(self.info)
        top.addLayout(tl, 1)
        self.time_btn = QPushButton("Correct date/time…")
        self.time_btn.clicked.connect(self._time)
        self.events_btn = QPushButton("Regroup events")
        self.events_btn.setToolTip("Rebuild the events (bursts) using the project's time gap")
        self.events_btn.clicked.connect(self._regroup)
        self.sort_btn = QPushButton("Copy into subfolders…")
        self.sort_btn.setToolTip("Copy files into Wildlife / People & livestock / Empty / Uncertain folders")
        self.sort_btn.clicked.connect(self._sort)
        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(lambda: open_file(db.get_deployment(self.con, self.deployment_id)["folder"]))
        for b in (self.open_btn, self.time_btn, self.events_btn, self.sort_btn):
            top.addWidget(b)
        lay.addLayout(top)

        # run panel
        run = QFrame()
        run.setObjectName("Card")
        rl = QVBoxLayout(run)
        rl.setContentsMargins(16, 12, 16, 12)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Find empty files (run MegaDetector)")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton("Pause")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.use_gpu = QCheckBox("Use graphics card if possible")
        self.use_gpu.setChecked(True)
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.use_gpu)
        row.addStretch()
        self.eta = QLabel()
        self.eta.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {theme.OLIVE_DARK};")
        row.addWidget(self.eta)
        rl.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        rl.addWidget(self.bar)
        self.status = QLabel()
        self.status.setObjectName("TileNote")
        rl.addWidget(self.status)
        lay.addWidget(run)

        tiles = QGridLayout()
        tiles.setSpacing(10)
        self.tiles = {}
        for i, g in enumerate(("animal", "uncertain", "human", "empty", "pending")):
            t = Tile(GROUP_LABELS.get(g, "Still to process"))
            t.v.setStyleSheet(f"color: {theme.GROUP_COLOURS[g]};")
            self.tiles[g] = t
            tiles.addWidget(t, 0, i)
        lay.addLayout(tiles)

        self.tabs = QTabWidget()
        self.grid = ReviewGrid(con)
        self.labeller = Labeller(con)
        self.tabs.addTab(self.grid, "1.  Check empty files")
        self.tabs.addTab(self.labeller, "2.  Label animals")
        self.tabs.currentChanged.connect(self._tab_changed)
        lay.addWidget(self.tabs, 1)
        self.grid.changed.connect(self._refresh_counts)
        self.labeller.changed.connect(self.changed)

    def busy(self):
        return bool((self.worker and self.worker.isRunning()) or (self.sort_worker and self.sort_worker.isRunning()))

    def load(self, deployment_id):
        if self.busy() and deployment_id != self.deployment_id:
            QMessageBox.information(self, "Busy", "Another deployment is still being processed. "
                                    "You can look at it, but pause it before starting another one.")
        self.deployment_id = deployment_id
        d = db.get_deployment(self.con, deployment_id)
        self.title.setText(d["name"])
        off = d["time_offset_seconds"]
        self.info.setText(
            f"Station {d['station_name']}  ·  {d['start_date']} → {d['end_date']}  ·  Camera: {d['camera'] or '–'}"
            + (f"  ·  <span style='color:{theme.OCHRE_DARK}'>time corrected {off:+d} s</span>" if off else "")
            + f"<br>{d['folder']}"
            + ("" if Path(d["folder"]).is_dir() else f"<br><b style='color:{theme.RED}'>Folder not found – is the drive connected?</b>")
        )
        self._refresh_counts()
        self.grid.load(deployment_id)
        self.labeller.load(deployment_id)
        self.tabs.setCurrentIndex(0)

    def _refresh_counts(self):
        d = db.get_deployment(self.con, self.deployment_id)
        p = db.get_project(self.con, d["project_id"])
        c = labels.group_counts(self.con, self.deployment_id, p["animal_threshold"], p["uncertain_threshold"])
        errors = self.con.execute(
            "SELECT COUNT(*) FROM media WHERE deployment_id=? AND error IS NOT NULL", (self.deployment_id,)
        ).fetchone()[0]
        total = sum(c.values())
        for g, t in self.tiles.items():
            n = c.get(g, 0)
            if g == "pending":
                n -= errors
                t.set(f"{n:,}", f"{errors} unreadable" if errors else "")
            else:
                t.set(f"{n:,}", f"{100 * n / total:.0f} %" if total else "")
        todo = c.get("pending", 0) - errors
        if not total:
            self.run_btn.setText("Find empty files (run MegaDetector)")
            self.status.setText("Not processed yet. Click the green button to start; you can pause and continue later.")
        else:
            self.run_btn.setText("Continue processing" if todo > 0 else "Check folder for new files")
        self.sort_btn.setEnabled(total > 0 and todo == 0)

    def _tab_changed(self, i):
        if i == 1:
            self.labeller.reload(keep=True)
        else:
            self.grid.reload()

    # ------------------------------------------------------------ processing
    def _run(self):
        d = db.get_deployment(self.con, self.deployment_id)
        if not Path(d["folder"]).is_dir():
            QMessageBox.warning(self, "Folder not found", f"Cannot find:\n{d['folder']}")
            return
        p = db.get_project(self.con, d["project_id"])
        self.worker = ProcessWorker(self.db_path, self.deployment_id, p["event_gap_seconds"], self.use_gpu.isChecked())
        self.worker.progress.connect(self._progress)
        self.worker.status.connect(self.status.setText)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.tracker = ProgressTracker()
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.eta.setText("Starting…")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()

    def _progress(self, done, total, name):
        pct, rate, eta, elapsed = self.tracker.update(done, total)
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.bar.setFormat(f"{pct:.0f} %   ({done:,} of {total:,})")
        self.eta.setText(
            f"{pct:.0f} %  ·  about {fmt_duration(eta)} left" if eta is not None else f"{pct:.0f} %  ·  estimating time…")
        speed = f"{rate:.1f} files/s" if rate >= 1 else (f"{60 * rate:.0f} files/min" if rate > 0 else "")
        self.status.setText(f"{name}   ·   {speed}   ·   running for {fmt_duration(elapsed)}")
        if done % 25 == 0:
            self._refresh_counts()

    def _stop(self):
        for w in (self.worker, self.sort_worker):
            if w and w.isRunning():
                w.stop()
        self.status.setText("Pausing after the current file… (click Continue later to resume)")

    def _done(self, res):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.eta.setText("Paused" if res["remaining"] else "Done ✔")
        msg = f"Processed {res['processed']:,} files on {res['device']} in {fmt_duration(time.monotonic() - self.tracker.start)}."
        if res.get("new_files"):
            msg = f"{res['new_files']:,} new files found. " + msg
        if res["errors"]:
            msg += f" {res['errors']} file(s) could not be read."
        if res["remaining"]:
            msg += f" Paused: {res['remaining']:,} files left."
        if "events" in res:
            msg += f" Grouped into {res['events']:,} events."
        self.load(self.deployment_id)
        self.status.setText(msg)
        self.changed.emit()

    def _failed(self, err):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.eta.setText("")
        self.status.setText("")
        QMessageBox.critical(self, "Processing stopped", err)
        self._refresh_counts()

    # ------------------------------------------------------------ sorting
    def _sort(self):
        d = db.get_deployment(self.con, self.deployment_id)
        default = Path(d["folder"]) / sorting.SORTED_DIR
        box = QMessageBox(self)
        box.setWindowTitle("Copy into subfolders")
        box.setText(
            "Copies of the files will be put in four folders:<br><br>"
            "• <b>Wildlife</b> – animals (and files you labelled with wild species)<br>"
            "• <b>People &amp; livestock</b> – people, vehicles, and files labelled with Domestic/Human species<br>"
            "• <b>Empty</b><br>• <b>Uncertain</b> – not yet checked or labelled<br><br>"
            f"Default location:<br><code>{default}</code><br><br>"
            "Your original files stay where they are. Label first if you want livestock separated from wildlife."
        )
        here = box.addButton("Copy to default location", QMessageBox.ButtonRole.AcceptRole)
        other = box.addButton("Choose another folder…", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is here:
            dest = None
        elif box.clickedButton() is other:
            dest = QFileDialog.getExistingDirectory(self, "Where should the sorted copies go?")
            if not dest:
                return
            dest = str(Path(dest) / d["name"])
        else:
            return
        self.sort_worker = SortWorker(self.db_path, self.deployment_id, dest)
        self.sort_worker.progress.connect(self._progress)
        self.sort_worker.finished_ok.connect(self._sorted)
        self.sort_worker.failed.connect(self._failed)
        self.tracker = ProgressTracker()
        self.bar.setVisible(True)
        self.run_btn.setEnabled(False)
        self.sort_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.eta.setText("Copying…")
        self.sort_worker.start()

    def _sorted(self, res):
        self.bar.setVisible(False)
        self.run_btn.setEnabled(True)
        self.sort_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.eta.setText("Copied ✔")
        c = res["counts"]
        self.status.setText(" · ".join(f"{k}: {v:,}" for k, v in c.items()) + f"   →  {res['dest']}")
        if QMessageBox.question(self, "Copied", "Files copied:\n\n" + "\n".join(f"{k}: {v:,}" for k, v in c.items())
                                + f"\n\n(Already there, skipped: {res['skipped']:,})\n\nOpen the folder?") \
                == QMessageBox.StandardButton.Yes:
            open_file(res["dest"])

    # ------------------------------------------------------------ tools
    def _time(self):
        dlg = TimeCorrectionDialog(self, self.con, self.deployment_id)
        if dlg.exec() and dlg.first_ts is not None:
            db.update_deployment(self.con, self.deployment_id, time_offset_seconds=dlg.offset)
            self.load(self.deployment_id)
            self.changed.emit()

    def _regroup(self):
        d = db.get_deployment(self.con, self.deployment_id)
        p = db.get_project(self.con, d["project_id"])
        try:
            n = processing.build_events(self.con, self.deployment_id, p["event_gap_seconds"])
        except RuntimeError:
            if QMessageBox.question(
                self, "Labels will be lost",
                "This deployment already has species labels. Regrouping deletes them. Continue?",
            ) != QMessageBox.StandardButton.Yes:
                return
            n = processing.build_events(self.con, self.deployment_id, p["event_gap_seconds"], force=True)
        self.load(self.deployment_id)
        self.status.setText(f"Regrouped into {n:,} events (gap {p['event_gap_seconds']} s).")
        self.changed.emit()
