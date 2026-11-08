"""Main window: header bar, projects home page, and a workspace per project."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ctt import __version__, db
from .assets import asset_path
from .dashboard import ProjectPage
from .deployment_page import DeploymentPage
from .dialogs import DeploymentDialog, ProjectDialog, SpeciesDialog, StationDialog
from .home import HomePage
from .station_page import StationPage

ROLE = Qt.ItemDataRole.UserRole


def covers_dir() -> Path:
    d = Path(os.environ.get("APPDATA") or Path.home()) / "CameraTrapTool" / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


class MainWindow(QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = str(db_path or db.default_db_path())
        self.con = db.connect(self.db_path)
        self.project_id = None
        self.setWindowTitle("Camera Trap Tool")
        self.setWindowIcon(QIcon(str(asset_path("app.ico"))))
        self.resize(1520, 940)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.home = HomePage(self.con)
        self.home.open_project.connect(self.open_project)
        self.home.new_project.connect(self.new_project)
        self.home.edit_project.connect(self.edit_project)
        self.home.delete_project.connect(self.delete_project)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self._workspace())
        self.go_home()

    # ------------------------------------------------------------ header
    def _header(self):
        h = QFrame()
        h.setObjectName("Header")
        h.setFixedHeight(58)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(14, 6, 14, 6)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(asset_path("logo_64.png"))).scaled(
            42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setCursor(Qt.CursorShape.PointingHandCursor)
        logo.mousePressEvent = lambda _e: self.go_home()
        lay.addWidget(logo)
        title = QLabel("Camera Trap Tool")
        title.setObjectName("HeaderTitle")
        lay.addWidget(title)
        lay.addSpacing(16)
        self.crumb = QLabel()
        self.crumb.setObjectName("Crumb")
        self.crumb.setTextFormat(Qt.TextFormat.RichText)
        self.crumb.linkActivated.connect(self._crumb_link)
        lay.addWidget(self.crumb, 1)
        for text, fn in (("Projects", self.go_home), ("Species list", self.species_list)):
            b = QPushButton(text)
            b.setObjectName("HeaderButton")
            b.clicked.connect(fn)
            lay.addWidget(b)
        helpb = QPushButton("Help ▾")
        helpb.setObjectName("HeaderButton")
        m = QMenu(helpb)
        m.addAction("Open log folder", self._open_logs)
        m.addAction("Open data folder (database, backups)", self._open_data)
        m.addSeparator()
        m.addAction("About", self._about)
        helpb.setMenu(m)
        lay.addWidget(helpb)
        return h

    def _set_crumb(self, parts):
        """parts: list of (text, link or None)."""
        out = []
        for text, link in parts:
            out.append(f'<a href="{link}" style="color:#E8D6AE; text-decoration:none">{text}</a>' if link else text)
        self.crumb.setText("  ›  ".join(out))

    def _crumb_link(self, link):
        if link == "home":
            self.go_home()
        elif link.startswith("project:"):
            self._select(("project", self.project_id))
        elif link.startswith("station:"):
            self._select(("station", int(link.split(":")[1])))

    # ------------------------------------------------------------ workspace
    def _workspace(self):
        split = QSplitter(Qt.Orientation.Horizontal)
        side = QFrame()
        side.setObjectName("Sidebar")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 12, 10, 10)
        self.side_title = QLabel()
        self.side_title.setObjectName("SectionTitle")
        self.side_title.setWordWrap(True)
        sl.addWidget(self.side_title)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._edit(it))
        sl.addWidget(self.tree, 1)
        self.b_station = QPushButton("+  Add station")
        self.b_station.setObjectName("Primary")
        self.b_station.clicked.connect(self.add_station)
        self.b_dep = QPushButton("+  Add deployment")
        self.b_dep.clicked.connect(self._add_deployment_here)
        row = QHBoxLayout()
        self.b_edit = QPushButton("Edit")
        self.b_edit.clicked.connect(lambda: self._edit(self.tree.currentItem()))
        self.b_del = QPushButton("Delete")
        self.b_del.setObjectName("Danger")
        self.b_del.clicked.connect(self._delete)
        row.addWidget(self.b_edit)
        row.addWidget(self.b_del)
        sl.addWidget(self.b_station)
        sl.addWidget(self.b_dep)
        sl.addLayout(row)
        split.addWidget(side)

        self.pages = QStackedWidget()
        self.project_page = ProjectPage(self.con)
        self.station_page = StationPage(self.con)
        self.deployment_page = DeploymentPage(self.con, self.db_path)
        for w in (self.project_page, self.station_page, self.deployment_page):
            self.pages.addWidget(w)
        self.project_page.changed.connect(self._refresh_tree_keep)
        self.project_page.open_station.connect(lambda sid: self._select(("station", sid)))
        self.deployment_page.changed.connect(self._refresh_tree_keep)
        self.station_page.add_deployment.connect(self._add_deployment_to)
        self.station_page.open_deployment.connect(lambda did: self._select(("deployment", did)))
        self.station_page.edit_station.connect(lambda sid: self._edit(self._find(("station", sid))))
        split.addWidget(self.pages)
        split.setSizes([290, 1230])
        split.setStretchFactor(1, 1)
        return split

    # ------------------------------------------------------------ navigation
    def go_home(self):
        if self.deployment_page.busy():
            QMessageBox.information(self, "Busy", "Processing is still running in this project. "
                                    "Pause it first, or wait until it is finished.")
            return
        self.project_id = None
        self.home.reload()
        self.stack.setCurrentWidget(self.home)
        self._set_crumb([("Projects", None)])

    def open_project(self, pid):
        self.project_id = pid
        p = db.get_project(self.con, pid)
        self.side_title.setText(p["name"])
        self.stack.setCurrentIndex(1)
        logging.info("Open project %s", pid)
        self.refresh_tree(("project", pid))

    def refresh_tree(self, select=None):
        if self.project_id is None:
            return
        self.tree.blockSignals(True)
        self.tree.clear()
        p = db.get_project(self.con, self.project_id)
        root = QTreeWidgetItem(["📊  Dashboard"])
        root.setData(0, ROLE, ("project", p["id"]))
        self.tree.addTopLevelItem(root)
        target = root if select in (None, ("project", p["id"])) else None
        for s in db.list_stations(self.con, p["id"]):
            si = QTreeWidgetItem([f"📍  {s['name']}"])
            si.setData(0, ROLE, ("station", s["id"]))
            self.tree.addTopLevelItem(si)
            if select == ("station", s["id"]):
                target = si
            for d in db.list_deployments(self.con, s["id"]):
                mark = "✔" if d["processed_at"] else "○"
                di = QTreeWidgetItem([f"{mark}  {d['name']}"])
                di.setData(0, ROLE, ("deployment", d["id"]))
                di.setToolTip(0, d["folder"])
                si.addChild(di)
                if select == ("deployment", d["id"]):
                    target = di
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.tree.setCurrentItem(target or root)

    def _refresh_tree_keep(self):
        it = self.tree.currentItem()
        sel = it.data(0, ROLE) if it else None
        self.tree.blockSignals(True)
        self.refresh_tree_silent(sel)
        self.tree.blockSignals(False)

    def refresh_tree_silent(self, sel):
        """Update tree labels without reloading the open page."""
        self.tree.clear()
        p = db.get_project(self.con, self.project_id)
        root = QTreeWidgetItem(["📊  Dashboard"])
        root.setData(0, ROLE, ("project", p["id"]))
        self.tree.addTopLevelItem(root)
        for s in db.list_stations(self.con, p["id"]):
            si = QTreeWidgetItem([f"📍  {s['name']}"])
            si.setData(0, ROLE, ("station", s["id"]))
            self.tree.addTopLevelItem(si)
            for d in db.list_deployments(self.con, s["id"]):
                di = QTreeWidgetItem([f"{'✔' if d['processed_at'] else '○'}  {d['name']}"])
                di.setData(0, ROLE, ("deployment", d["id"]))
                si.addChild(di)
        self.tree.expandAll()
        it = self._find(sel)
        if it:
            self.tree.setCurrentItem(it)

    def _select(self, key):
        it = self._find(key)
        if it:
            self.tree.setCurrentItem(it)
        else:
            self.refresh_tree(key)

    def _find(self, key):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, ROLE) == key:
                return it
            stack.extend(it.child(i) for i in range(it.childCount()))
        return None

    def _selected(self, item, _prev=None):
        if not item:
            return
        kind, rid = item.data(0, ROLE)
        p = db.get_project(self.con, self.project_id)
        crumbs = [("Projects", "home"), (p["name"], f"project:{p['id']}")]
        self.b_dep.setEnabled(kind in ("station", "deployment"))
        self.b_edit.setEnabled(True)
        self.b_del.setEnabled(True)
        logging.info("Open %s %s", kind, rid)
        if kind == "project":
            self.project_page.load(rid)
            self.pages.setCurrentWidget(self.project_page)
            crumbs[-1] = (p["name"], None)
        elif kind == "station":
            self.station_page.load(rid)
            self.pages.setCurrentWidget(self.station_page)
            s = self.con.execute("SELECT name FROM station WHERE id=?", (rid,)).fetchone()
            crumbs.append((s["name"], None))
        else:
            self.deployment_page.load(rid)
            self.pages.setCurrentWidget(self.deployment_page)
            d = db.get_deployment(self.con, rid)
            crumbs += [(d["station_name"], f"station:{d['station_id']}"), (d["name"], None)]
        self._set_crumb(crumbs)

    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        menu = QMenu(self)
        if it is None:
            menu.addAction("Add station…", self.add_station)
        else:
            kind, rid = it.data(0, ROLE)
            if kind == "project":
                menu.addAction("Add station…", self.add_station)
                menu.addAction("Edit project…", lambda: self.edit_project(rid))
            elif kind == "station":
                menu.addAction("Add deployment…", lambda: self._add_deployment_to(rid))
                menu.addAction("Edit station…", lambda: self._edit(it))
                menu.addAction("Delete station", self._delete)
            else:
                menu.addAction("Edit deployment…", lambda: self._edit(it))
                menu.addAction("Delete deployment", self._delete)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ projects
    def _store_cover(self, path, pid):
        """Keep a copy of the cover photo, so the card still works if the original moves."""
        if not path:
            return ""
        src = Path(path)
        if src.parent == covers_dir():
            return str(src)
        dst = covers_dir() / f"project_{pid}{src.suffix.lower()}"
        try:
            shutil.copy2(src, dst)
            return str(dst)
        except OSError:
            return str(src)

    def new_project(self):
        dlg = ProjectDialog(self)
        if not dlg.exec():
            return
        v = dlg.values()
        try:
            pid = db.add_project(self.con, v["name"], v["notes"], "", v["location"])
        except Exception as exc:
            QMessageBox.warning(self, "Not saved", f"Could not create the project: {exc}")
            return
        db.update_project(self.con, pid, event_gap_seconds=v["event_gap_seconds"],
                          photo_path=self._store_cover(v["photo_path"], pid))
        self.open_project(pid)

    def edit_project(self, pid):
        dlg = ProjectDialog(self, db.get_project(self.con, pid))
        if dlg.exec():
            v = dlg.values()
            v["photo_path"] = self._store_cover(v["photo_path"], pid)
            try:
                db.update_project(self.con, pid, **v)
            except Exception as exc:
                QMessageBox.warning(self, "Not saved", str(exc))
            if self.project_id == pid:
                self.side_title.setText(v["name"])
                self.refresh_tree(("project", pid))
            else:
                self.home.reload()

    def delete_project(self, pid):
        p = db.get_project(self.con, pid)
        if QMessageBox.question(
            self, "Delete project",
            f"Delete project '{p['name']}' with all its stations, deployments and labels?\n\n"
            "Your image and video files are NOT deleted.",
        ) == QMessageBox.StandardButton.Yes:
            db.delete_project(self.con, pid)
            self.go_home()

    # ------------------------------------------------------------ stations / deployments
    def _stations(self):
        return db.list_stations(self.con, self.project_id)

    def add_station(self):
        dlg = StationDialog(self, None, self._stations())
        if dlg.exec():
            try:
                sid = db.add_station(self.con, self.project_id, **dlg.values())
            except Exception as exc:
                QMessageBox.warning(self, "Not saved", f"Could not add the station: {exc}")
                return
            self.refresh_tree(("station", sid))

    def _add_deployment_here(self):
        it = self.tree.currentItem()
        if not it:
            return
        kind, rid = it.data(0, ROLE)
        if kind == "deployment":
            rid = db.get_deployment(self.con, rid)["station_id"]
        if kind in ("station", "deployment"):
            self._add_deployment_to(rid)

    def _add_deployment_to(self, station_id):
        dlg = DeploymentDialog(self)
        if dlg.exec():
            did = db.add_deployment(self.con, station_id, **dlg.values())
            self.refresh_tree(("deployment", did))

    def _edit(self, it):
        if it is None:
            return
        kind, rid = it.data(0, ROLE)
        if kind == "project":
            return self.edit_project(rid)
        if kind == "station":
            row = self.con.execute("SELECT * FROM station WHERE id=?", (rid,)).fetchone()
            dlg = StationDialog(self, row, self._stations())
            if dlg.exec():
                try:
                    db.update_station(self.con, rid, **dlg.values())
                except Exception as exc:
                    QMessageBox.warning(self, "Not saved", str(exc))
        else:
            dlg = DeploymentDialog(self, db.get_deployment(self.con, rid))
            if dlg.exec():
                db.update_deployment(self.con, rid, **dlg.values())
        self.refresh_tree((kind, rid))

    def _delete(self):
        it = self.tree.currentItem()
        if it is None:
            return
        kind, rid = it.data(0, ROLE)
        if kind == "project":
            return self.delete_project(rid)
        name = it.text(0).split("  ", 1)[-1]
        if QMessageBox.question(
            self, "Delete",
            f"Delete {kind} '{name}' and everything under it (including labels)?\n"
            "Your image and video files are NOT deleted.",
        ) != QMessageBox.StandardButton.Yes:
            return
        (db.delete_station if kind == "station" else db.delete_deployment)(self.con, rid)
        self.refresh_tree(("project", self.project_id))

    # ------------------------------------------------------------ misc
    def species_list(self):
        SpeciesDialog(self, self.con).exec()
        if self.project_id is not None and self.pages.currentWidget() is self.deployment_page:
            self.deployment_page.labeller.refresh_species()

    def _open_logs(self):
        from .util import open_file

        open_file(Path(os.environ.get("APPDATA") or Path.home()) / "CameraTrapTool" / "logs")

    def _open_data(self):
        from .util import open_file

        open_file(Path(self.db_path).parent)

    def _about(self):
        QMessageBox.about(
            self, "About",
            f"<b>Camera Trap Tool {__version__}</b><br>Finds empty camera trap images and videos with "
            "MegaDetector v5a (Beery et al. 2019) and helps you label the rest by hand.<br><br>"
            "Map data © OpenStreetMap contributors; imagery © Esri. Elevation: Copernicus DEM via open-meteo.com.<br>"
            "Inspired by AddaxAI (van Lunteren 2023). Your original files are never moved or changed.",
        )

    def closeEvent(self, e):
        w = self.deployment_page.worker
        if w and w.isRunning():
            w.stop()
            w.wait(15000)
        super().closeEvent(e)
