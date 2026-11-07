"""One deployment: process it, check empty files, label animals, fix time."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from ctt import db, labels, processing
from ctt.grouping import GROUP_LABELS
from .dialogs import TimeCorrectionDialog
from .labeller import Labeller
from .review_grid import ReviewGrid
from .workers import ProcessWorker


class DeploymentPage(QWidget):
    changed = Signal()

    def __init__(self, con, db_path):
        super().__init__()
        self.con = con
        self.db_path = db_path
        self.deployment_id = None
        self.worker = None

        lay = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: bold")
        lay.addWidget(self.title)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        row = QHBoxLayout()
        self.run_btn = QPushButton("Find empty files (run MegaDetector)")
        self.run_btn.setStyleSheet("font-weight:bold; padding:6px 12px")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton("Pause")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.use_gpu = QCheckBox("Use graphics card if possible")
        self.use_gpu.setChecked(True)
        self.time_btn = QPushButton("Correct date/time…")
        self.time_btn.clicked.connect(self._time)
        self.events_btn = QPushButton("Regroup events")
        self.events_btn.setToolTip("Rebuild the events (bursts) using the project's time gap")
        self.events_btn.clicked.connect(self._regroup)
        for w in (self.run_btn, self.stop_btn, self.use_gpu):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.time_btn)
        row.addWidget(self.events_btn)
        lay.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel()
        lay.addWidget(self.status)
        self.counts = QLabel()
        self.counts.setStyleSheet("font-size: 14px")
        lay.addWidget(self.counts)

        self.tabs = QTabWidget()
        self.grid = ReviewGrid(con)
        self.labeller = Labeller(con)
        self.tabs.addTab(self.grid, "1. Check empty files")
        self.tabs.addTab(self.labeller, "2. Label animals")
        self.tabs.currentChanged.connect(self._tab_changed)
        lay.addWidget(self.tabs, 1)
        self.grid.changed.connect(self._refresh_counts)
        self.labeller.changed.connect(self.changed)

    def load(self, deployment_id):
        self.deployment_id = deployment_id
        d = db.get_deployment(self.con, deployment_id)
        self.title.setText(f"Deployment: {d['name']}  (station {d['station_name']})")
        off = d["time_offset_seconds"]
        self.info.setText(
            f"Folder: {d['folder']}<br>Dates: {d['start_date']} → {d['end_date']}  ·  Camera: {d['camera'] or '-'}"
            + (f"  ·  <span style='color:#b26a00'>Time corrected by {off:+d} s</span>" if off else "")
            + ("" if Path(d["folder"]).is_dir() else "<br><b style='color:#c62828'>Folder not found — is the drive connected?</b>")
        )
        self._refresh_counts()
        self.grid.load(deployment_id)
        self.labeller.load(deployment_id)

    def _refresh_counts(self):
        d = db.get_deployment(self.con, self.deployment_id)
        p = db.get_project(self.con, d["project_id"])
        c = labels.group_counts(self.con, self.deployment_id, p["animal_threshold"], p["uncertain_threshold"])
        total = sum(c.values())
        if not total:
            self.counts.setText("Not processed yet. Click 'Find empty files' to start.")
            return
        parts = [f"<b>{GROUP_LABELS[g]}</b>: {c.get(g, 0)}" for g in ("animal", "uncertain", "human", "empty")]
        pending = c.get("pending", 0)
        errors = self.con.execute(
            "SELECT COUNT(*) FROM media WHERE deployment_id=? AND error IS NOT NULL", (self.deployment_id,)
        ).fetchone()[0]
        txt = f"{total} files  —  " + "   ".join(parts)
        if pending:
            txt += f"   ·   {pending - errors} still to process"
        if errors:
            txt += f"   ·   <span style='color:#c62828'>{errors} unreadable</span>"
        self.counts.setText(txt)
        self.run_btn.setText("Continue processing" if pending - errors > 0 else "Find empty files (run MegaDetector)")

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
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()

    def _progress(self, done, total, name):
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.bar.setFormat(f"{done} / {total}  —  {name}")
        if done % 25 == 0:
            self._refresh_counts()

    def _stop(self):
        if self.worker:
            self.worker.stop()
            self.status.setText("Pausing after the current file… (click Continue later to resume)")

    def _done(self, res):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setVisible(False)
        msg = f"Processed {res['processed']} files on {res['device']}."
        if res["errors"]:
            msg += f" {res['errors']} file(s) could not be read."
        if res["remaining"]:
            msg += f" Paused: {res['remaining']} files left."
        if "events" in res:
            msg += f" Grouped into {res['events']} events."
        self.status.setText(msg)
        self.load(self.deployment_id)
        self.changed.emit()

    def _failed(self, err):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.status.setText("")
        QMessageBox.critical(self, "Processing stopped", err)
        self._refresh_counts()

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
        self.status.setText(f"Regrouped into {n} events (gap {p['event_gap_seconds']} s).")
        self.load(self.deployment_id)
        self.changed.emit()
