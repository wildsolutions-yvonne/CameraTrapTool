"""Background threads so the window stays responsive."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ctt import db, processing


class ProcessWorker(QThread):
    """Scan folder, run MegaDetector, then build events."""

    progress = Signal(int, int, str)
    status = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, db_path, deployment_id, gap_seconds, prefer_gpu=True):
        super().__init__()
        self.db_path = db_path
        self.deployment_id = deployment_id
        self.gap_seconds = gap_seconds
        self.prefer_gpu = prefer_gpu
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            con = db.connect(self.db_path)  # own connection: sqlite objects are per-thread
            self.status.emit("Looking for images and videos…")
            new = processing.scan_deployment(con, self.deployment_id)
            self.status.emit("Loading MegaDetector…")
            from ctt.detector import MegaDetector

            det = MegaDetector(prefer_gpu=self.prefer_gpu)
            self.status.emit(f"Detecting animals using: {det.device_label}")
            res = processing.run_detection(
                con, self.deployment_id, det,
                progress=lambda d, t, f: self.progress.emit(d, t, f),
                should_stop=lambda: self._stop,
            )
            res["new_files"] = new
            res["device"] = det.device_label
            if res["remaining"] == 0:
                has_events = con.execute(
                    "SELECT COUNT(*) FROM event WHERE deployment_id=?", (self.deployment_id,)
                ).fetchone()[0]
                if not has_events or new:
                    try:
                        res["events"] = processing.build_events(con, self.deployment_id, self.gap_seconds)
                    except RuntimeError as exc:
                        res["events_note"] = str(exc)
            con.close()
            self.finished_ok.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class ThumbnailWorker(QThread):
    """Loads thumbnails one by one and emits them as they are ready."""

    ready = Signal(int, QImage)

    def __init__(self, items, size=200):
        """items: list of (key, path, kind, seconds)."""
        super().__init__()
        self.items = items
        self.size = size
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from .util import load_image

        for key, path, kind, seconds in self.items:
            if self._stop:
                return
            try:
                img = load_image(Path(path), kind, seconds, self.size)
            except Exception:
                img = QImage()
            self.ready.emit(key, img)
