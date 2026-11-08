"""Main window: project/station/deployment tree on the left, pages on the right."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QMenu,
)

from ctt import __version__, db
from .dashboard import ProjectPage
from .deployment_page import DeploymentPage
from .dialogs import DeploymentDialog, ProjectDialog, SpeciesDialog, StationDialog

ROLE = Qt.ItemDataRole.UserRole


class MainWindow(QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = str(db_path or db.default_db_path())
        self.con = db.connect(self.db_path)
        self.setWindowTitle(f"Camera Trap Tool {__version__}")
        self.resize(1500, 900)

        menu = self.menuBar()
        m = menu.addMenu("&File")
        a = QAction("New project…", self)
        a.triggered.connect(self.new_project)
        m.addAction(a)
        m.addSeparator()
        q = QAction("Quit", self)
        q.triggered.connect(self.close)
        m.addAction(q)
        s = menu.addMenu("&Settings")
        sp = QAction("Species list…", self)
        sp.triggered.connect(lambda: SpeciesDialog(self, self.con).exec())
        s.addAction(sp)
        h = menu.addMenu("&Help")
        lg = QAction("Open log folder", self)
        lg.triggered.connect(self._open_logs)
        h.addAction(lg)
        ab = QAction("About", self)
        ab.triggered.connect(self._about)
        h.addAction(ab)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Projects › Stations › Deployments</b>"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._edit(it))
        ll.addWidget(self.tree)
        btns = QHBoxLayout()
        self.b_add = QPushButton("+ Add")
        self.b_add.setToolTip("Add a project, or a station/deployment under the selected item")
        self.b_add.clicked.connect(self._add)
        self.b_edit = QPushButton("Edit")
        self.b_edit.clicked.connect(lambda: self._edit(self.tree.currentItem()))
        self.b_del = QPushButton("Delete")
        self.b_del.clicked.connect(self._delete)
        for b in (self.b_add, self.b_edit, self.b_del):
            btns.addWidget(b)
        ll.addLayout(btns)
        split.addWidget(left)

        self.stack = QStackedWidget()
        self.welcome = QLabel(
            "<h2>Welcome</h2><p>1. Create a <b>project</b> (File → New project).<br>"
            "2. Add <b>stations</b> (camera locations, with GPS) to it.<br>"
            "3. Add a <b>deployment</b> for each camera visit and choose its SD-card folder.<br>"
            "4. Open the deployment and click <b>Find empty files</b>.<br>"
            "5. Check the empty files, then label the animals.</p>"
            "<p>Set up your species list under Settings → Species list.</p>"
        )
        self.welcome.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.welcome.setMargin(20)
        self.project_page = ProjectPage(self.con)
        self.deployment_page = DeploymentPage(self.con, self.db_path)
        self.project_page.changed.connect(self._refresh_tree_keep)
        self.deployment_page.changed.connect(self._refresh_tree_keep)
        for w in (self.welcome, self.project_page, self.deployment_page):
            self.stack.addWidget(w)
        split.addWidget(self.stack)
        split.setSizes([300, 1200])
        self.setCentralWidget(split)
        self.refresh_tree()

    # ------------------------------------------------------------ tree
    def refresh_tree(self, select=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        target = None
        for p in db.list_projects(self.con):
            pi = QTreeWidgetItem([f"📁 {p['name']}"])
            pi.setData(0, ROLE, ("project", p["id"]))
            self.tree.addTopLevelItem(pi)
            for s in db.list_stations(self.con, p["id"]):
                si = QTreeWidgetItem([f"📍 {s['name']}"])
                si.setData(0, ROLE, ("station", s["id"]))
                pi.addChild(si)
                for d in db.list_deployments(self.con, s["id"]):
                    mark = "✔" if d["processed_at"] else "○"
                    di = QTreeWidgetItem([f"{mark} {d['name']}"])
                    di.setData(0, ROLE, ("deployment", d["id"]))
                    si.addChild(di)
                    if select == ("deployment", d["id"]):
                        target = di
                if select == ("station", s["id"]):
                    target = si
            if select == ("project", p["id"]):
                target = pi
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if target:
            self.tree.setCurrentItem(target)
        elif self.tree.topLevelItemCount() == 0:
            self.stack.setCurrentWidget(self.welcome)

    def _refresh_tree_keep(self):
        it = self.tree.currentItem()
        sel = it.data(0, ROLE) if it else None
        self.tree.blockSignals(True)
        self.refresh_tree()
        self.tree.blockSignals(False)
        # re-select silently (without reloading the page)
        if sel:
            for item in self._all_items():
                if item.data(0, ROLE) == sel:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    self.tree.blockSignals(False)

    def _all_items(self):
        out = []
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            out.append(it)
            stack.extend(it.child(i) for i in range(it.childCount()))
        return out

    def _selected(self, item, _prev=None):
        if not item:
            self.stack.setCurrentWidget(self.welcome)
            return
        kind, rid = item.data(0, ROLE)
        import logging

        logging.info("Open %s %s", kind, rid)
        if kind == "deployment":
            self.deployment_page.load(rid)
            self.stack.setCurrentWidget(self.deployment_page)
        else:
            pid = rid if kind == "project" else self.con.execute(
                "SELECT project_id FROM station WHERE id=?", (rid,)).fetchone()[0]
            self.project_page.load(pid)
            self.stack.setCurrentWidget(self.project_page)

    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        menu = QMenu(self)
        if it is None:
            menu.addAction("New project…", self.new_project)
        else:
            kind, _ = it.data(0, ROLE)
            if kind == "project":
                menu.addAction("Add station…", self._add)
            elif kind == "station":
                menu.addAction("Add deployment…", self._add)
            menu.addAction("Edit…", lambda: self._edit(it))
            menu.addAction("Delete", self._delete)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ add/edit/delete
    def new_project(self):
        dlg = ProjectDialog(self)
        if dlg.exec():
            v = dlg.values()
            if not v["name"]:
                return
            try:
                pid = db.add_project(self.con, v["name"], v["notes"])
                db.update_project(self.con, pid, event_gap_seconds=v["event_gap_seconds"])
            except Exception as exc:
                QMessageBox.warning(self, "Not saved", f"Could not create project: {exc}")
                return
            self.refresh_tree(("project", pid))

    def _add(self):
        it = self.tree.currentItem()
        if it is None:
            return self.new_project()
        kind, rid = it.data(0, ROLE)
        if kind == "project":
            dlg = StationDialog(self)
            if dlg.exec() and dlg.values()["name"]:
                try:
                    sid = db.add_station(self.con, rid, **dlg.values())
                except Exception as exc:
                    QMessageBox.warning(self, "Not saved", str(exc))
                    return
                self.refresh_tree(("station", sid))
        elif kind == "station":
            dlg = DeploymentDialog(self)
            if dlg.exec():
                did = db.add_deployment(self.con, rid, **dlg.values())
                self.refresh_tree(("deployment", did))
        else:
            parent = it.parent()
            self.tree.setCurrentItem(parent)
            self._add()

    def _edit(self, it):
        if it is None:
            return
        kind, rid = it.data(0, ROLE)
        if kind == "project":
            dlg = ProjectDialog(self, db.get_project(self.con, rid))
            if dlg.exec():
                db.update_project(self.con, rid, **dlg.values())
        elif kind == "station":
            row = self.con.execute("SELECT * FROM station WHERE id=?", (rid,)).fetchone()
            dlg = StationDialog(self, row)
            if dlg.exec():
                db.update_station(self.con, rid, **dlg.values())
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
        name = it.text(0)[2:]
        if QMessageBox.question(
            self, "Delete",
            f"Delete {kind} '{name}' and everything under it (including labels)?\n"
            "Your image and video files are NOT deleted.",
        ) != QMessageBox.StandardButton.Yes:
            return
        {"project": db.delete_project, "station": db.delete_station, "deployment": db.delete_deployment}[kind](self.con, rid)
        self.refresh_tree()

    def _open_logs(self):
        import os
        from pathlib import Path

        from .util import open_file

        open_file(Path(os.environ.get("APPDATA") or Path.home()) / "CameraTrapTool" / "logs")

    def _about(self):
        QMessageBox.about(
            self, "About",
            f"<b>Camera Trap Tool {__version__}</b><br>Finds empty camera trap images and videos with "
            "MegaDetector v5a (Beery et al.; Microsoft AI for Earth) and helps you label the rest by hand.<br><br>"
            "Inspired by AddaxAI (Peter van Lunteren). Your original files are never moved or changed.",
        )

    def closeEvent(self, e):
        w = self.deployment_page.worker
        if w and w.isRunning():
            w.stop()
            w.wait(15000)
        super().closeEvent(e)
