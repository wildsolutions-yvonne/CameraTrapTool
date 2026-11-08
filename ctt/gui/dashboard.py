"""Project dashboard: station map, summary charts, thresholds and export."""

from __future__ import annotations

import json
from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QHeaderView,
)

from ctt import db, export, labels
from ctt.grouping import GROUP_LABELS
from ctt.processing import corrected_time

LEAFLET_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%;margin:0}</style></head><body><div id="m"></div><script>
var pts = __POINTS__;
if (typeof L === 'undefined') {
  document.body.innerHTML = '<p style="font-family:sans-serif;padding:1em">The map needs an internet connection. '
   + 'Stations: ' + pts.map(p => p.name + ' (' + p.lat.toFixed(5) + ', ' + p.lon.toFixed(5) + ')').join(', ') + '</p>';
} else {
  var map = L.map('m');
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18,
     attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
  var group = [];
  pts.forEach(function(p){ var mk = L.marker([p.lat, p.lon]).addTo(map).bindPopup('<b>'+p.name+'</b><br>'+p.info);
     mk.bindTooltip(p.name, {permanent: true, direction: 'right'}); group.push([p.lat, p.lon]); });
  if (group.length) map.fitBounds(group, {padding: [40, 40], maxZoom: 14}); else map.setView([0.0, 37.0], 6);
}
</script></body></html>"""


class MapWidget(QWidget):
    """Station positions drawn in the window, plus a button for an interactive
    OpenStreetMap in the normal web browser (needs internet)."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = _ScatterMap()
        lay.addWidget(self.view)
        self.btn = QPushButton("Open interactive map in web browser")
        self.btn.clicked.connect(self._open_browser)
        lay.addWidget(self.btn)
        self.points = []

    def show_points(self, points):
        self.points = points
        self.view.plot(points)
        self.btn.setEnabled(bool(points))

    def _open_browser(self):
        import tempfile
        import webbrowser
        from pathlib import Path

        path = Path(tempfile.gettempdir()) / "cameratraptool_map.html"
        path.write_text(LEAFLET_HTML.replace("__POINTS__", json.dumps(self.points)), encoding="utf-8")
        webbrowser.open(path.as_uri())


class _ScatterMap(QWidget):
    """Fallback map without background tiles."""

    def __init__(self):
        super().__init__()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.fig = Figure(figsize=(4, 3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        QVBoxLayout(self).addWidget(self.canvas)

    def plot(self, points):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        for p in points:
            ax.plot(p["lon"], p["lat"], "o", color="#2e7d32")
            ax.annotate(p["name"], (p["lon"], p["lat"]), xytext=(4, 4), textcoords="offset points")
        if not points:
            ax.text(0.5, 0.5, "No stations with GPS yet", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal", adjustable="datalim")
        self.canvas.draw()


class ChartsWidget(QWidget):
    def __init__(self):
        super().__init__()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Chart:"))
        self.kind = QComboBox()
        self.kind.addItems([
            "Events per species",
            "Events per station",
            "Activity by hour of day (all species)",
            "Activity by hour of day (selected species)",
        ])
        self.species = QComboBox()
        top.addWidget(self.kind)
        top.addWidget(self.species)
        top.addStretch()
        lay.addLayout(top)
        self.fig = Figure(figsize=(6, 3.5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        lay.addWidget(self.canvas)
        self.kind.currentIndexChanged.connect(self.redraw)
        self.species.currentIndexChanged.connect(self.redraw)
        self.records = []

    def set_records(self, records):
        """records: list of dicts {station, species, hour} - one per labelled event x species."""
        self.records = records
        cur = self.species.currentText()
        self.species.blockSignals(True)
        self.species.clear()
        self.species.addItems(sorted({r["species"] for r in records}))
        if cur:
            self.species.setCurrentText(cur)
        self.species.blockSignals(False)
        self.redraw()

    def redraw(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        k = self.kind.currentIndex()
        self.species.setVisible(k == 3)
        recs = self.records
        if not recs:
            ax.text(0.5, 0.5, "No labelled events yet", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
        elif k in (0, 1):
            key = "species" if k == 0 else "station"
            c = Counter(r[key] for r in recs).most_common()
            names = [n for n, _ in c][::-1]
            ax.barh(names, [v for _, v in c][::-1], color="#2e7d32")
            ax.set_xlabel("Number of events (independent detections)")
        else:
            sel = recs if k == 2 else [r for r in recs if r["species"] == self.species.currentText()]
            hours = Counter(r["hour"] for r in sel if r["hour"] is not None)
            ax.bar(range(24), [hours.get(h, 0) for h in range(24)], color="#6d4c41")
            ax.set_xticks(range(0, 24, 2))
            ax.set_xlabel("Hour of day")
            ax.set_ylabel("Events")
        self.canvas.draw()


class ProjectPage(QWidget):
    changed = Signal()

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.project_id = None
        lay = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: bold")
        lay.addWidget(self.title)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.map = MapWidget()
        ll.addWidget(self.map, 3)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Station", "Deployments", "Files", "Animal", "Uncertain", "Human/Veh.", "Empty"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        ll.addWidget(self.table, 2)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.charts = ChartsWidget()
        rl.addWidget(self.charts, 3)

        thr = QGroupBox("Detection thresholds (apply to the whole project)")
        tf = QFormLayout(thr)
        self.animal_thr = QDoubleSpinBox()
        self.uncertain_thr = QDoubleSpinBox()
        for sb in (self.animal_thr, self.uncertain_thr):
            sb.setRange(0.01, 0.99)
            sb.setSingleStep(0.01)
            sb.setDecimals(2)
        tf.addRow("Animal if confidence at least", self.animal_thr)
        tf.addRow("Uncertain if confidence at least", self.uncertain_thr)
        tf.addRow(QLabel("Below the 'uncertain' value a file counts as Empty. Lower values = fewer animals missed, more files to check."))
        save_thr = QPushButton("Apply thresholds")
        save_thr.clicked.connect(self._save_thresholds)
        tf.addRow(save_thr)
        rl.addWidget(thr)

        exp = QGroupBox("Export")
        el = QHBoxLayout(exp)
        self.include_empty = QCheckBox("Include empty files")
        b = QPushButton("Export to Excel / CSV…")
        b.clicked.connect(self._export)
        el.addWidget(self.include_empty)
        el.addStretch()
        el.addWidget(b)
        rl.addWidget(exp)
        split.addWidget(right)
        split.setSizes([500, 600])
        lay.addWidget(split)

    def load(self, project_id):
        self.project_id = project_id
        p = db.get_project(self.con, project_id)
        self.title.setText(f"Project: {p['name']}")
        self.animal_thr.setValue(p["animal_threshold"])
        self.uncertain_thr.setValue(p["uncertain_threshold"])
        a, u = p["animal_threshold"], p["uncertain_threshold"]

        stations = db.list_stations(self.con, project_id)
        points = []
        self.table.setRowCount(len(stations))
        for i, s in enumerate(stations):
            deps = db.list_deployments(self.con, s["id"])
            tot = Counter()
            for d in deps:
                tot.update(labels.group_counts(self.con, d["id"], a, u))
            n_files = sum(tot.values())
            vals = [s["name"], len(deps), n_files, tot["animal"], tot["uncertain"], tot["human"], tot["empty"]]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
            if s["latitude"] is not None:
                points.append({
                    "name": s["name"], "lat": s["latitude"], "lon": s["longitude"],
                    "info": f"{len(deps)} deployment(s), {n_files} files, {tot['animal']} with animals",
                })
        self.map.show_points(points)
        self.charts.set_records(self._chart_records(project_id))

    def _chart_records(self, project_id):
        rows = self.con.execute(
            """SELECT DISTINCT e.id ev, s.name station, sp.common_name species, e.start_at, d.time_offset_seconds off
               FROM label l JOIN species sp ON sp.id=l.species_id
               JOIN event e ON e.id=l.event_id JOIN deployment d ON d.id=e.deployment_id
               JOIN station s ON s.id=d.station_id WHERE s.project_id=?""",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            ts = corrected_time(r["start_at"], r["off"])
            out.append({"station": r["station"], "species": r["species"], "hour": ts.hour if ts else None})
        return out

    def _save_thresholds(self):
        a, u = self.animal_thr.value(), self.uncertain_thr.value()
        if u >= a:
            QMessageBox.warning(self, "Thresholds", "The 'uncertain' value must be lower than the 'animal' value.")
            return
        db.update_project(self.con, self.project_id, animal_threshold=a, uncertain_threshold=u)
        self.load(self.project_id)
        self.changed.emit()

    def _export(self):
        p = db.get_project(self.con, self.project_id)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", f"{p['name']}_observations.xlsx", "Excel (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            n = export.export_project(self.con, self.project_id, path, self.include_empty.isChecked())
            QMessageBox.information(self, "Exported", f"{n} rows written to\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
