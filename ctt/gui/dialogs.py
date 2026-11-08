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
        from .home import cover_pixmap

        self._cover = cover_pixmap
        self.setWindowTitle("Project")
        self.resize(560, 520)
        f = QFormLayout(self)
        self.name = QLineEdit(row["name"] if row else "")
        self.name.setPlaceholderText("e.g. Tumbili 2026")
        self.location = QLineEdit(row["location"] if row else "")
        self.location.setPlaceholderText("e.g. Laikipia, Kenya")
        self.photo_path = row["photo_path"] if row else ""
        self.preview = QLabel()
        self.preview.setFixedSize(300, 170)
        pick = QPushButton("Choose photo…")
        pick.clicked.connect(self._pick)
        clear = QPushButton("Remove photo")
        clear.clicked.connect(lambda: self._set_photo(""))
        prow = QHBoxLayout()
        prow.addWidget(pick)
        prow.addWidget(clear)
        prow.addStretch()
        pw = QWidget()
        pw.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        self.notes = QTextEdit(row["notes"] if row else "")
        self.notes.setFixedHeight(70)
        self.gap = QSpinBox()
        self.gap.setRange(1, 7200)
        self.gap.setSuffix(" s")
        self.gap.setValue(row["event_gap_seconds"] if row else 60)
        self.gap.setToolTip("Files closer together than this belong to the same event. "
                            "Use 1800 s (30 min) for the usual independence rule in RAI.")
        f.addRow("Project name", self.name)
        f.addRow("Area / location", self.location)
        f.addRow("Cover photo", self.preview)
        f.addRow("", pw)
        f.addRow("Notes", self.notes)
        f.addRow("Same event if files are less than", self.gap)
        f.addRow(_buttons(self))
        self._set_photo(self.photo_path)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cover photo", "", "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)")
        if path:
            self._set_photo(path)

    def _set_photo(self, path):
        self.photo_path = path
        self.preview.setPixmap(self._cover(path, self.name.text() or "Project", 300, 170))

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing", "Please give the project a name.")
            return
        super().accept()

    def values(self):
        return dict(name=self.name.text().strip(), notes=self.notes.toPlainText(),
                    event_gap_seconds=self.gap.value(), photo_path=self.photo_path,
                    location=self.location.text().strip())


class StationDialog(QDialog):
    """Station name + location: click on the map, pick a GPS waypoint, or type coordinates."""

    def __init__(self, parent=None, row=None, other_stations=()):
        super().__init__(parent)
        from PySide6.QtNetwork import QNetworkAccessManager

        from .mapview import MapWidget

        self.setWindowTitle("Station (camera location)")
        self.resize(1100, 680)
        self.net = QNetworkAccessManager(self)
        self.net.finished.connect(self._elevation_reply)
        self._busy = False

        outer = QHBoxLayout(self)
        # ---- left: form + waypoints
        left = QVBoxLayout()
        f = QFormLayout()
        self.name = QLineEdit(row["name"] if row else "")
        self.lat = QDoubleSpinBox()
        self.lat.setRange(-90, 90)
        self.lat.setDecimals(6)
        self.lon = QDoubleSpinBox()
        self.lon.setRange(-180, 180)
        self.lon.setDecimals(6)
        self.ele = QDoubleSpinBox()
        self.ele.setRange(-500, 9000)
        self.ele.setDecimals(0)
        self.ele.setSuffix(" m")
        self.ele.setSpecialValueText("unknown")
        self.ele.setMinimum(-500)
        self.ele.setValue(-500)
        if row and row["latitude"] is not None:
            self.lat.setValue(row["latitude"])
            self.lon.setValue(row["longitude"])
        if row and row["elevation"] is not None:
            self.ele.setValue(row["elevation"])
        self.notes = QLineEdit(row["notes"] if row else "")
        self.notes.setPlaceholderText("habitat, placement, height…")
        f.addRow("Station name", self.name)
        f.addRow("Latitude", self.lat)
        f.addRow("Longitude", self.lon)
        erow = QHBoxLayout()
        erow.addWidget(self.ele, 1)
        look = QPushButton("Look up")
        look.setToolTip("Fetch the elevation for these coordinates (needs internet)")
        look.clicked.connect(self._lookup_elevation)
        erow.addWidget(look)
        ew = QWidget()
        ew.setLayout(erow)
        erow.setContentsMargins(0, 0, 0, 0)
        f.addRow("Elevation", ew)
        f.addRow("Notes", self.notes)
        left.addLayout(f)
        self.status = QLabel("Click on the map to set the location, or pick a waypoint below.")
        self.status.setWordWrap(True)
        self.status.setObjectName("TileNote")
        left.addWidget(self.status)

        left.addSpacing(8)
        wh = QHBoxLayout()
        t = QLabel("GPS waypoints")
        t.setObjectName("SectionTitle")
        wh.addWidget(t)
        wh.addStretch()
        imp = QPushButton("Import GPX / CSV / Excel…")
        imp.clicked.connect(self._import)
        wh.addWidget(imp)
        left.addLayout(wh)
        self.wp_filter = QLineEdit(placeholderText="Search waypoints…")
        self.wp_filter.textChanged.connect(self._filter_wps)
        left.addWidget(self.wp_filter)
        self.wp_list = QTableWidget(0, 3)
        self.wp_list.setHorizontalHeaderLabels(["Name", "Lat / Lon", "Elev."])
        self.wp_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.wp_list.horizontalHeader().setStretchLastSection(True)
        self.wp_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.wp_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.wp_list.verticalHeader().setVisible(False)
        self.wp_list.itemSelectionChanged.connect(self._wp_selected)
        left.addWidget(self.wp_list, 1)
        bb = _buttons(self)
        left.addWidget(bb)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(400)
        outer.addWidget(lw)

        # ---- right: map
        self.map = MapWidget()
        outer.addWidget(self.map, 1)
        self.map.canvas.clicked.connect(self._map_clicked)
        self.map.canvas.marker_clicked.connect(self._marker_picked)
        others = [
            {"lat": o["latitude"], "lon": o["longitude"], "label": o["name"], "colour": "#8E8A7E", "radius": 5}
            for o in other_stations if o["latitude"] is not None and (not row or o["id"] != row["id"])
        ]
        self.map.canvas.set_markers(others, fit=True)
        if row and row["latitude"] is not None:
            self.map.canvas.set_pick(row["latitude"], row["longitude"])
        self.lat.valueChanged.connect(self._coords_typed)
        self.lon.valueChanged.connect(self._coords_typed)
        self.waypoints = []

    # ---- location
    def _has_coords(self):
        return not (self.lat.value() == 0 and self.lon.value() == 0)

    def _map_clicked(self, lat, lon):
        self._set_location(lat, lon, None, center=False)
        self.status.setText(f"Location set from map: {lat:.6f}, {lon:.6f}")

    def _coords_typed(self):
        if self._busy or not self._has_coords():
            return
        self.map.canvas.set_pick(self.lat.value(), self.lon.value(), center=True)

    def _set_location(self, lat, lon, elevation, center=True):
        self._busy = True
        self.lat.setValue(lat)
        self.lon.setValue(lon)
        self._busy = False
        self.map.canvas.set_pick(lat, lon, center=center)
        if elevation is not None:
            self.ele.setValue(elevation)
        else:
            self._lookup_elevation()

    def _lookup_elevation(self):
        if not self._has_coords():
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtNetwork import QNetworkRequest

        url = QUrl(f"https://api.open-meteo.com/v1/elevation?latitude={self.lat.value():.6f}&longitude={self.lon.value():.6f}")
        self.net.get(QNetworkRequest(url))
        self.status.setText("Looking up elevation…")

    def _elevation_reply(self, reply):
        import json

        from PySide6.QtNetwork import QNetworkReply

        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                ele = json.loads(bytes(reply.readAll()))["elevation"][0]
                self.ele.setValue(round(float(ele)))
                self.status.setText(f"Elevation {ele:.0f} m (from Copernicus DEM via open-meteo.com). You can correct it.")
            else:
                self.status.setText("No internet: elevation not looked up. Type it in, or use a GPS file with elevation.")
        except Exception:
            self.status.setText("Elevation lookup failed; please type it in.")
        reply.deleteLater()

    # ---- waypoints
    def _import(self):
        from ctt import gps

        path, _ = QFileDialog.getOpenFileName(
            self, "GPS waypoints", "", "GPS files (*.gpx *.csv *.txt *.xlsx);;All files (*)")
        if not path:
            return
        try:
            wps = gps.read_waypoints(path)
        except Exception as exc:
            QMessageBox.warning(self, "Could not read file", str(exc))
            return
        if not wps:
            QMessageBox.information(self, "No waypoints", "No waypoints found in this file.")
            return
        self.waypoints = wps
        self._filter_wps()
        self.map.canvas.set_markers(
            self.map.canvas.markers + [
                {"lat": w.lat, "lon": w.lon, "label": w.name, "colour": "#3E6E8E", "radius": 5, "key": i}
                for i, w in enumerate(wps)
            ], fit=True)
        self.status.setText(f"{len(wps)} waypoints loaded. Click one in the list or on the map.")

    def _filter_wps(self):
        q = self.wp_filter.text().strip().lower()
        shown = [(i, w) for i, w in enumerate(self.waypoints) if q in w.name.lower()]
        self.wp_list.blockSignals(True)
        self.wp_list.setRowCount(len(shown))
        for r, (i, w) in enumerate(shown):
            a = QTableWidgetItem(w.name)
            a.setData(Qt.ItemDataRole.UserRole, i)
            self.wp_list.setItem(r, 0, a)
            self.wp_list.setItem(r, 1, QTableWidgetItem(f"{w.lat:.5f}, {w.lon:.5f}"))
            self.wp_list.setItem(r, 2, QTableWidgetItem("" if w.elevation is None else f"{w.elevation:.0f} m"))
        self.wp_list.blockSignals(False)

    def _wp_selected(self):
        rows = self.wp_list.selectionModel().selectedRows()
        if rows:
            self._marker_picked(self.wp_list.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def _marker_picked(self, i):
        if not isinstance(i, int) or i >= len(self.waypoints):
            return
        w = self.waypoints[i]
        if not self.name.text().strip():
            self.name.setText(w.name)
        self._set_location(w.lat, w.lon, w.elevation)
        self.status.setText(f"Waypoint {w.name}: {w.lat:.6f}, {w.lon:.6f}")

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing", "Please give the station a name.")
            return
        super().accept()

    def values(self):
        has = self._has_coords()
        ele = self.ele.value()
        return dict(
            name=self.name.text().strip(),
            latitude=self.lat.value() if has else None,
            longitude=self.lon.value() if has else None,
            elevation=None if ele <= -500 else ele,
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


class SpeciesEditDialog(QDialog):
    def __init__(self, parent, row=None):
        super().__init__(parent)
        from ctt.db import TAXON_GROUPS

        self.setWindowTitle("Edit species" if row else "Add species")
        f = QFormLayout(self)
        self.common = QLineEdit(row["common_name"] if row else "")
        self.common.setPlaceholderText("e.g. Kirk's dik-dik")
        self.sci = QLineEdit((row["scientific_name"] or "") if row else "")
        self.sci.setPlaceholderText("e.g. Madoqua kirkii")
        from PySide6.QtWidgets import QComboBox

        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItems([""] + TAXON_GROUPS)
        self.group.setCurrentText((row["taxon_group"] or "") if row else "")
        f.addRow("Common name", self.common)
        f.addRow("Scientific name", self.sci)
        f.addRow("Taxon group", self.group)
        hint = QLabel("Species in the groups <b>Domestic</b> or <b>Human</b> are treated as people &amp; livestock "
                      "(own subfolder, not counted as wildlife in the statistics).")
        hint.setWordWrap(True)
        hint.setObjectName("TileNote")
        f.addRow(hint)
        f.addRow(_buttons(self))

    def accept(self):
        if not self.common.text().strip():
            QMessageBox.warning(self, "Missing", "Please enter a common name.")
            return
        super().accept()

    def values(self):
        return dict(common_name=self.common.text().strip(), scientific_name=self.sci.text().strip(),
                    taxon_group=self.group.currentText().strip())


class SpeciesDialog(QDialog):
    """The master species list, shared by all projects: add, edit, delete, import."""

    def __init__(self, parent, con):
        super().__init__(parent)
        self.con = con
        self.setWindowTitle("Species list")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        t = QLabel("Species list")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        sub = QLabel("One list for all projects. Double-click a species to edit it.")
        sub.setObjectName("PageSubtitle")
        lay.addWidget(sub)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("🔍  Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._reload)
        lay.addWidget(self.search)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Common name", "Scientific name", "Taxon group", "Labels"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._edit())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("+  Add species")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit…")
        edit.clicked.connect(self._edit)
        dele = QPushButton("Delete")
        dele.setObjectName("Danger")
        dele.clicked.connect(self._delete)
        imp = QPushButton("Import CSV / Excel…")
        imp.setToolTip("Columns: common name, scientific name (optional), taxon group (optional)")
        imp.clicked.connect(self._import)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for w in (add, edit, dele, imp):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self._reload()

    def _reload(self, *_):
        q = self.search.text().strip().lower()
        sp = [s for s in db.list_species(self.con)
              if not q or q in f"{s['common_name']} {s['scientific_name']} {s['taxon_group']}".lower()]
        used = dict(self.con.execute("SELECT species_id, COUNT(*) FROM label GROUP BY species_id").fetchall())
        self.table.setRowCount(len(sp))
        for i, s in enumerate(sp):
            a = QTableWidgetItem(s["common_name"])
            a.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.table.setItem(i, 0, a)
            sci = QTableWidgetItem(s["scientific_name"] or "")
            f = sci.font()
            f.setItalic(True)
            sci.setFont(f)
            self.table.setItem(i, 1, sci)
            self.table.setItem(i, 2, QTableWidgetItem(s["taxon_group"] or ""))
            n = QTableWidgetItem(str(used.get(s["id"], 0)))
            n.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 3, n)

    def _selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole), self.table.item(r, 0).text()) for r in rows]

    def _add(self):
        dlg = SpeciesEditDialog(self)
        if dlg.exec():
            v = dlg.values()
            if self.con.execute("SELECT 1 FROM species WHERE common_name=? COLLATE NOCASE", (v["common_name"],)).fetchone():
                QMessageBox.warning(self, "Already there", f"'{v['common_name']}' is already in the list.")
                return
            db.add_species(self.con, v["common_name"], v["scientific_name"], v["taxon_group"])
            self._reload()

    def _edit(self):
        sel = self._selected_ids()
        if not sel:
            return
        row = self.con.execute("SELECT * FROM species WHERE id=?", (sel[0][0],)).fetchone()
        dlg = SpeciesEditDialog(self, row)
        if dlg.exec():
            try:
                db.update_species(self.con, row["id"], **dlg.values())
            except ValueError as exc:
                QMessageBox.warning(self, "Not saved", str(exc))
            self._reload()

    def _delete(self):
        sel = self._selected_ids()
        if not sel:
            return
        names = ", ".join(n for _i, n in sel)
        if QMessageBox.question(self, "Delete species", f"Delete {names}?") != QMessageBox.StandardButton.Yes:
            return
        for sid, name in sel:
            n = db.species_usage(self.con, sid)
            if n:
                QMessageBox.warning(self, "Cannot delete",
                                    f"{name} is used in {n} label(s). Change those labels first, "
                                    "or edit the species instead (e.g. rename it).")
                continue
            db.delete_species(self.con, sid)
        self._reload()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Species list", "", "Species list (*.csv *.txt *.xlsx)")
        if path:
            try:
                n = db.import_species_table(self.con, path)
                QMessageBox.information(self, "Imported", f"{n} species imported (existing names were updated).")
            except Exception as exc:
                QMessageBox.critical(self, "Import failed", str(exc))
            self._reload()
