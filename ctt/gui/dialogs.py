"""Forms for projects, stations, deployments, species and time correction."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtWidgets import (
    QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QAbstractItemView,
)

from ctt import db
from ctt.processing import parse_ts


def _buttons(dlg):
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class ProjectDialog(QDialog):
    def __init__(self, parent=None, row=None):
        super().__init__(parent)
        self.setWindowTitle("Project")
        f = QFormLayout(self)
        self.name = QLineEdit(row["name"] if row else "")
        self.notes = QTextEdit(row["notes"] if row else "")
        self.notes.setFixedHeight(80)
        self.gap = QSpinBox()
        self.gap.setRange(1, 3600)
        self.gap.setSuffix(" s")
        self.gap.setValue(row["event_gap_seconds"] if row else 60)
        f.addRow("Project name", self.name)
        f.addRow("Notes", self.notes)
        f.addRow("Photos belong to the same event if less than", self.gap)
        f.addRow(_buttons(self))

    def values(self):
        return dict(name=self.name.text().strip(), notes=self.notes.toPlainText(), event_gap_seconds=self.gap.value())


class StationDialog(QDialog):
    def __init__(self, parent=None, row=None):
        super().__init__(parent)
        self.setWindowTitle("Station (camera location)")
        f = QFormLayout(self)
        self.name = QLineEdit(row["name"] if row else "")
        self.lat = QDoubleSpinBox()
        self.lat.setRange(-90, 90)
        self.lat.setDecimals(6)
        self.lon = QDoubleSpinBox()
        self.lon.setRange(-180, 180)
        self.lon.setDecimals(6)
        if row and row["latitude"] is not None:
            self.lat.setValue(row["latitude"])
            self.lon.setValue(row["longitude"])
        self.notes = QLineEdit(row["notes"] if row else "")
        f.addRow("Station name", self.name)
        f.addRow("Latitude (decimal degrees)", self.lat)
        f.addRow("Longitude (decimal degrees)", self.lon)
        f.addRow(QLabel("Tip: south of the equator, latitude is negative (e.g. -1.2921)."))
        f.addRow("Notes / habitat", self.notes)
        f.addRow(_buttons(self))

    def values(self):
        lat, lon = self.lat.value(), self.lon.value()
        has = not (lat == 0 and lon == 0)
        return dict(
            name=self.name.text().strip(),
            latitude=lat if has else None,
            longitude=lon if has else None,
            notes=self.notes.text(),
        )


class DeploymentDialog(QDialog):
    def __init__(self, parent=None, row=None):
        super().__init__(parent)
        self.setWindowTitle("Deployment (one camera visit)")
        f = QFormLayout(self)
        self.name = QLineEdit(row["name"] if row else "")
        self.folder = QLineEdit(row["folder"] if row else "")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        frow = QHBoxLayout()
        frow.addWidget(self.folder)
        frow.addWidget(browse)
        fw = QWidget()
        fw.setLayout(frow)
        self.start = QDateEdit(calendarPopup=True)
        self.end = QDateEdit(calendarPopup=True)
        for w, key in ((self.start, "start_date"), (self.end, "end_date")):
            w.setDisplayFormat("yyyy-MM-dd")
            val = row[key] if row else ""
            w.setDate(QDate.fromString(val, "yyyy-MM-dd") if val else QDate.currentDate())
        self.camera = QLineEdit(row["camera"] if row else "")
        self.notes = QLineEdit(row["notes"] if row else "")
        f.addRow("Deployment name", self.name)
        f.addRow("Folder with images/videos", fw)
        f.addRow("Start date", self.start)
        f.addRow("End date", self.end)
        f.addRow("Camera (model / serial)", self.camera)
        f.addRow("Notes", self.notes)
        f.addRow(_buttons(self))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the folder with this deployment's files", self.folder.text())
        if d:
            self.folder.setText(d)
            if not self.name.text():
                from pathlib import Path

                self.name.setText(Path(d).name)

    def accept(self):
        if not self.name.text().strip() or not self.folder.text().strip():
            QMessageBox.warning(self, "Missing", "Please give a name and choose a folder.")
            return
        super().accept()

    def values(self):
        return dict(
            name=self.name.text().strip(),
            folder=self.folder.text().strip(),
            start_date=self.start.date().toString("yyyy-MM-dd"),
            end_date=self.end.date().toString("yyyy-MM-dd"),
            camera=self.camera.text(),
            notes=self.notes.text(),
        )


class TimeCorrectionDialog(QDialog):
    """Pick the correct date/time for the first file; the same shift is applied to all."""

    def __init__(self, parent, con, deployment_id):
        super().__init__(parent)
        self.setWindowTitle("Correct date and time")
        dep = db.get_deployment(con, deployment_id)
        first = con.execute(
            "SELECT relpath, taken_at FROM media WHERE deployment_id=? AND taken_at IS NOT NULL ORDER BY taken_at LIMIT 1",
            (deployment_id,),
        ).fetchone()
        self.offset = dep["time_offset_seconds"]
        lay = QVBoxLayout(self)
        if not first:
            lay.addWidget(QLabel("Process the deployment first, so the file times are known."))
            lay.addWidget(_buttons(self))
            self.first_ts = None
            return
        self.first_ts = parse_ts(first["taken_at"])
        lay.addWidget(QLabel(
            f"First file: <b>{first['relpath']}</b><br>"
            f"Time recorded by the camera: <b>{self.first_ts:%Y-%m-%d %H:%M:%S}</b><br><br>"
            "Enter the date and time this file was <i>really</i> taken. "
            "All files in this deployment will be shifted by the same amount.<br>"
            "(The original files are not changed; only the times used in the app and exports.)"
        ))
        self.edit = QDateTimeEdit(calendarPopup=True)
        self.edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        corrected = self.first_ts + dt.timedelta(seconds=self.offset)
        self.edit.setDateTime(corrected)
        self.edit.dateTimeChanged.connect(self._update)
        lay.addWidget(self.edit)
        self.info = QLabel()
        lay.addWidget(self.info)
        reset = QPushButton("Remove correction")
        reset.clicked.connect(lambda: self.edit.setDateTime(self.first_ts))
        lay.addWidget(reset)
        lay.addWidget(_buttons(self))
        self._update()

    def _update(self):
        right = self.edit.dateTime().toPython()
        self.offset = int((right - self.first_ts).total_seconds())
        d = dt.timedelta(seconds=abs(self.offset))
        sign = "later" if self.offset >= 0 else "earlier"
        self.info.setText("No shift." if self.offset == 0 else f"All times will be shifted {d} {sign}.")


class SpeciesDialog(QDialog):
    """The master species list, shared by all projects."""

    def __init__(self, parent, con):
        super().__init__(parent)
        self.con = con
        self.setWindowTitle("Species list")
        self.resize(560, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("One list for all projects. Double-click a cell to edit."))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Common name", "Scientific name"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.new_common = QLineEdit(placeholderText="Common name")
        self.new_sci = QLineEdit(placeholderText="Scientific name (optional)")
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        row.addWidget(self.new_common)
        row.addWidget(self.new_sci)
        row.addWidget(add)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        imp = QPushButton("Import from CSV / Excel…")
        imp.clicked.connect(self._import)
        dele = QPushButton("Delete selected")
        dele.clicked.connect(self._delete)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row2.addWidget(imp)
        row2.addWidget(dele)
        row2.addStretch()
        row2.addWidget(close)
        lay.addLayout(row2)
        self._reload()

    def _reload(self):
        self.table.blockSignals(True)
        sp = db.list_species(self.con)
        self.table.setRowCount(len(sp))
        for i, s in enumerate(sp):
            a = QTableWidgetItem(s["common_name"])
            a.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, QTableWidgetItem(s["scientific_name"] or ""))
        self.table.blockSignals(False)

    def _edited(self, item):
        sid = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        col = "common_name" if item.column() == 0 else "scientific_name"
        try:
            self.con.execute(f"UPDATE species SET {col}=? WHERE id=?", (item.text().strip(), sid))
            self.con.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Not saved", str(exc))
            self._reload()

    def _add(self):
        if self.new_common.text().strip():
            db.add_species(self.con, self.new_common.text(), self.new_sci.text())
            self.new_common.clear()
            self.new_sci.clear()
            self._reload()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Species list", "", "Species list (*.csv *.txt *.xlsx)")
        if path:
            try:
                n = db.import_species_table(self.con, path)
                QMessageBox.information(self, "Imported", f"{n} species imported (existing names were kept).")
            except Exception as exc:
                QMessageBox.critical(self, "Import failed", str(exc))
            self._reload()

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        for r in rows:
            sid = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            try:
                db.delete_species(self.con, sid)
            except ValueError as exc:
                QMessageBox.warning(self, "Cannot delete", f"{self.table.item(r, 0).text()}: {exc}")
        self._reload()
