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
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: bold")
        lay.addWidget(self.title)
        self.info = QLabel()
        lay.addWidget(self.info)
        edit = QPushButton("Edit station (name, GPS)…")
        edit.clicked.connect(lambda: self.edit_station.emit(self.station_id))
        edit.setMaximumWidth(260)
        lay.addWidget(edit)

        lay.addSpacing(12)
        lay.addWidget(QLabel(
            "<b>Deployments</b>: each camera visit to this station, linked to the folder with its photos/videos.<br>"
            "Double-click a deployment to open it."
        ))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Deployment", "Dates", "Folder", "Files", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._open)
        lay.addWidget(self.table, 1)

        add = QPushButton("+  Add deployment (choose folder with photos / videos)")
        add.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px")
        add.clicked.connect(lambda: self.add_deployment.emit(self.station_id))
        lay.addWidget(add)

    def load(self, station_id):
        self.station_id = station_id
        s = self.con.execute("SELECT * FROM station WHERE id=?", (station_id,)).fetchone()
        self.title.setText(f"Station: {s['name']}")
        gps = f"{s['latitude']:.6f}, {s['longitude']:.6f}" if s["latitude"] is not None else "no GPS yet"
        self.info.setText(f"GPS: {gps}" + (f"   ·   {s['notes']}" if s["notes"] else ""))
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
            vals = [d["name"], f"{d['start_date']} → {d['end_date']}", d["folder"], str(n), status]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, d["id"])
                self.table.setItem(i, j, it)

    def _open(self, row, _col):
        self.open_deployment.emit(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
