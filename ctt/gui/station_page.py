"""One station: its details and its deployments, with a clear 'add deployment' button."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ctt import db, labels


class StationPage(QWidget):
    add_deployment = Signal(int)      # station id
    open_deployment = Signal(int)     # deployment id
    edit_station = Signal(int)

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.station_id = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        lay.addWidget(self.title)
        self.info = QLabel()
        self.info.setObjectName("PageSubtitle")
        lay.addWidget(self.info)
        edit = QPushButton("Edit station (name, GPS)…")
        edit.clicked.connect(lambda: self.edit_station.emit(self.station_id))
        edit.setMaximumWidth(260)
        lay.addWidget(edit)

        lay.addSpacing(12)
        dt = QLabel("Deployments")
        dt.setObjectName("SectionTitle")
        lay.addWidget(dt)
        lay.addWidget(QLabel(
            "Each camera visit to this station, linked to the folder with its photos/videos.<br>"
            "Double-click a deployment to open it."
        ))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Deployment", "Start → end", "Folder", "Files", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._open)
        lay.addWidget(self.table, 1)

        add = QPushButton("Add deployment (choose folder with photos / videos)")
        from .icons import icon

        add.setIcon(icon("camera", "#FFFFFF", 20))
        add.setObjectName("Primary")
        add.setMinimumHeight(42)
        add.clicked.connect(lambda: self.add_deployment.emit(self.station_id))
        lay.addWidget(add)

    def load(self, station_id):
        self.station_id = station_id
        s = self.con.execute("SELECT * FROM station WHERE id=?", (station_id,)).fetchone()
        from ctt.geo import format_latlon

        self.title.setText(s["name"])
        gps = format_latlon(s["latitude"], s["longitude"]) if s["latitude"] is not None else "no GPS yet – click Edit station"
        ele = f"  ·  {s['elevation']:.0f} m" if s["elevation"] is not None else ""
        self.info.setText(f"{gps}{ele}" + (f"   ·   {s['notes']}" if s["notes"] else ""))
        p = self.con.execute("SELECT * FROM project WHERE id=?", (s["project_id"],)).fetchone()
        deps = db.list_deployments(self.con, station_id)
        self.table.setRowCount(len(deps))
        for i, d in enumerate(deps):
            c = labels.group_counts(self.con, d["id"], p["animal_threshold"], p["uncertain_threshold"])
            n = sum(c.values())
            if not Path(d["folder"]).is_dir():
                status = "Folder not found"
            elif d["processed_at"]:
                status = f"Processed: {c.get('animal', 0)} animal, {c.get('empty', 0)} empty"
            elif n:
                status = "Partly processed"
            else:
                status = "Not processed yet"
            start, end, src = db.deployment_period(self.con, d)
            when = (f"{start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M}" if start and end else "after processing")
            vals = [d["name"], when, d["folder"], str(n), status]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, d["id"])
                self.table.setItem(i, j, it)

    def _open(self, row, _col):
        self.open_deployment.emit(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
