"""Project dashboard: key numbers, station map, charts, tables, thresholds and exports."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QAbstractItemView,
)

from ctt import db, export, stats as S
from ctt.db import TAXON_GROUPS
from . import theme
from .icons import icon, pixmap
from .mapview import MapWidget


# ---------------------------------------------------------------- small widgets
class Tile(QFrame):
    clicked = Signal()

    def __init__(self, label, value="–", note="", clickable=False, icon_name=None, icon_color=None):
        super().__init__()
        self.setObjectName("Tile")
        if clickable:
            self.setProperty("clickable", True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)
        self.l = QLabel(label)
        self.l.setObjectName("TileLabel")
        top = QHBoxLayout()
        top.setSpacing(6)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(pixmap(icon_name, icon_color or theme.OLIVE, 18))
            top.addWidget(ic)
        top.addWidget(self.l, 1)
        self.v = QLabel(value)
        self.v.setObjectName("TileValue")
        self.n = QLabel(note)
        self.n.setObjectName("TileNote")
        self.n.setWordWrap(True)
        lay.addLayout(top)
        for w in (self.v, self.n):
            lay.addWidget(w)

    def set(self, value, note=""):
        self.v.setText(value)
        self.n.setText(note)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


def table(headers, stretch_last=False):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(stretch_last)
    t.setSortingEnabled(True)
    return t


class NumItem(QTableWidgetItem):
    """Sorts numerically; shows '–' for missing values."""

    def __init__(self, v, digits=1, pct=False):
        self.val = v
        if v is None:
            txt = "–"
        elif pct:
            txt = f"{100 * v:.1f} %"
        elif isinstance(v, float):
            txt = f"{v:,.{digits}f}"
        else:
            txt = f"{v:,}" if isinstance(v, int) else str(v)
        super().__init__(txt)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        a = self.val if self.val is not None else float("-inf")
        b = getattr(other, "val", None)
        b = b if b is not None else float("-inf")
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def fill(t, rows):
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            t.setItem(i, j, v if isinstance(v, QTableWidgetItem) else QTableWidgetItem("" if v is None else str(v)))
    t.setSortingEnabled(True)


# ---------------------------------------------------------------- charts
CHARTS = [
    "Records per species",
    "Share of records (pie)",
    "Records per station",
    "Species richness per station",
    "Wild RAI per station",
    "Activity by hour of day",
    "Activity overlap of two species",
    "Records per month",
    "Species accumulation",
    "Species × station (records)",
    "Trap-nights per station",
    "False-trigger rate per station",
]


class ChartsPanel(QWidget):
    def __init__(self):
        super().__init__()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        theme.apply_matplotlib_style()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Chart"))
        self.kind = QComboBox()
        self.kind.addItems(CHARTS)
        top.addWidget(self.kind)
        self.sp_a = QComboBox()
        self.sp_b = QComboBox()
        self.vs = QLabel("vs")
        for w in (self.sp_a, self.vs, self.sp_b):
            top.addWidget(w)
        top.addStretch()
        save = QPushButton("Save chart as image…")
        save.clicked.connect(self._save)
        top.addWidget(save)
        lay.addLayout(top)
        self.fig = Figure(figsize=(8, 4.5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        lay.addWidget(self.canvas, 1)
        self.note = QLabel()
        self.note.setObjectName("TileNote")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.kind.currentIndexChanged.connect(self.redraw)
        self.sp_a.currentIndexChanged.connect(self.redraw)
        self.sp_b.currentIndexChanged.connect(self.redraw)
        self.st = None
        self.taxon = None
        self.taxon_label = "All species"

    def set_data(self, st, taxon, taxon_label):
        self.st, self.taxon, self.taxon_label = st, taxon, taxon_label
        used = sorted({st.species[r.species_id]["common_name"]: r.species_id for r in st.records}.items())
        for cb in (self.sp_a, self.sp_b):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            for name, sid in used:
                cb.addItem(name, sid)
            if cur:
                cb.setCurrentText(cur)
            cb.blockSignals(False)
        if self.sp_b.count() > 1 and self.sp_b.currentIndex() == self.sp_a.currentIndex():
            self.sp_b.setCurrentIndex(1)
        self.redraw()

    def redraw(self):
        import numpy as np

        k = self.kind.currentText()
        overlap = k == "Activity overlap of two species"
        for w in (self.sp_a, self.vs, self.sp_b):
            w.setVisible(overlap)
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        self.note.setText("")
        st = self.st
        if st is None:
            return
        tx = self.taxon
        title_tx = f" – {self.taxon_label}" if tx else ""

        def empty(msg="No labelled records yet for this selection"):
            ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes, color=theme.MUTED)
            ax.set_axis_off()

        if k in ("Records per species", "Share of records (pie)"):
            rows = st.species_summary(tx)
            if not rows:
                empty()
            elif k.startswith("Records"):
                rows = rows[:30][::-1]
                ax.barh([r["species"] for r in rows], [r["records"] for r in rows], color=theme.OLIVE)
                for i, r in enumerate(rows):
                    ax.text(r["records"], i, f" {r['records']}", va="center", fontsize=8, color=theme.MUTED)
                ax.set_xlabel("Records (independent events)")
                ax.set_title("Records per species" + title_tx)
                ax.grid(axis="y", visible=False)
            else:
                top = rows[:9]
                rest = sum(r["records"] for r in rows[9:])
                vals = [r["records"] for r in top] + ([rest] if rest else [])
                labels = [r["species"] for r in top] + (["Other"] if rest else [])
                ax.pie(vals, labels=labels, autopct="%1.0f%%", startangle=90, colors=theme.CHART,
                       wedgeprops={"linewidth": 1.5, "edgecolor": "white"}, textprops={"fontsize": 8})
                ax.set_title("Share of records" + title_tx)
                ax.axis("equal")
        elif k in ("Records per station", "Species richness per station", "Wild RAI per station",
                   "Trap-nights per station", "False-trigger rate per station"):
            rows = st.station_summary()
            if not rows:
                return empty("No stations yet")
            if k == "Records per station":
                m = st.matrix(tx)
                vals = [sum(m[sid].get(r["station_id"], 0) for sid in m) for r in rows]
                xl = "Records" + title_tx
            elif k == "Species richness per station":
                vals, xl = [r["richness"] for r in rows], "Wild species recorded"
            elif k == "Wild RAI per station":
                vals, xl = [r["wild_rai"] or 0 for r in rows], "Wild records per 100 trap-nights"
            elif k == "Trap-nights per station":
                vals, xl = [r["trap_nights"] for r in rows], "Trap-nights"
                early = [r["station"] for r in rows if r["stopped_early"]]
                if early:
                    self.note.setText("Camera stopped before the planned end date at: " + ", ".join(early) +
                                      ". Trap-nights were counted up to the last file.")
            else:
                vals = [100 * (r["false_trigger_rate"] or 0) for r in rows]
                xl = "% of files without animal, person or vehicle"
            names = [r["station"] for r in rows]
            colours = [theme.OLIVE] * len(vals)
            if vals and k not in ("Trap-nights per station", "False-trigger rate per station") and max(vals) > 0:
                colours[int(np.argmax(vals))] = theme.OCHRE
            ax.bar(names, vals, color=colours)
            ax.set_ylabel(xl)
            ax.set_title(k)
            ax.grid(axis="x", visible=False)
            if len(names) > 8:
                ax.tick_params(axis="x", rotation=45)
        elif k == "Activity by hour of day":
            h = st.activity_hours(tx)
            if len(h) < 2:
                return empty("At least 2 records with a time are needed")
            ax.hist(h, bins=24, range=(0, 24), color=theme.OLIVE_LIGHT, edgecolor=theme.OLIVE, density=True, label="records")
            g, d = S.circular_density(h)
            ax.plot(g, d, color=theme.OCHRE, linewidth=2.2, label="smoothed")
            ax.axvspan(0, 6, color="#2B2A26", alpha=0.06)
            ax.axvspan(18.5, 24, color="#2B2A26", alpha=0.06)
            ax.set_xlim(0, 24)
            ax.set_xticks(range(0, 25, 3))
            ax.set_xlabel("Hour of day (shaded = night, approx.)")
            ax.set_ylabel("Density")
            ax.set_title(f"Activity pattern{title_tx}  (n = {len(h)})")
            ax.legend(frameon=False)
        elif k == "Activity overlap of two species":
            a, b = self.sp_a.currentData(), self.sp_b.currentData()
            if a is None or b is None or a == b:
                return empty("Choose two different species above")
            ha, hb = st.activity_hours(("species", a)), st.activity_hours(("species", b))
            ov = S.activity_overlap(ha, hb)
            if ov is None:
                return empty("Each species needs at least 2 records with a time")
            g, da = S.circular_density(ha)
            _, db_ = S.circular_density(hb)
            ax.plot(g, da, color=theme.OLIVE, linewidth=2.2, label=f"{self.sp_a.currentText()} (n={len(ha)})")
            ax.plot(g, db_, color=theme.OCHRE, linewidth=2.2, label=f"{self.sp_b.currentText()} (n={len(hb)})")
            ax.fill_between(g, np.minimum(da, db_), color=theme.OLIVE_LIGHT, alpha=0.9, label=f"overlap Δ = {ov:.2f}")
            ax.set_xlim(0, 24)
            ax.set_xticks(range(0, 25, 3))
            ax.set_xlabel("Hour of day")
            ax.set_ylabel("Density")
            ax.set_title("Activity overlap")
            ax.legend(frameon=False)
            self.note.setText("Overlap Δ ranges from 0 (never active at the same time) to 1 (identical pattern). "
                              "Small samples (< 20 records) give uncertain values.")
        elif k == "Records per month":
            m = st.monthly(tx)
            if not m:
                return empty()
            ax.bar(list(m), list(m.values()), color=theme.OLIVE)
            ax.set_ylabel("Records")
            ax.set_title("Records per month" + title_tx)
            ax.grid(axis="x", visible=False)
            if len(m) > 8:
                ax.tick_params(axis="x", rotation=45)
        elif k == "Species accumulation":
            acc = st.accumulation()
            if not acc:
                return empty()
            ax.step([d for d, _ in acc], [n for _, n in acc], where="post", color=theme.OLIVE, linewidth=2.2)
            ax.plot([d for d, _ in acc], [n for _, n in acc], "o", color=theme.OCHRE, markersize=4)
            ax.set_ylabel("Wild species recorded (cumulative)")
            ax.set_title("Species accumulation over the survey")
            self.fig.autofmt_xdate()
            self.note.setText("If the curve is still rising at the end, more species are likely to be found with more effort.")
        elif k == "Species × station (records)":
            rows = st.species_summary(tx)
            stations = st.stations
            if not rows or not stations:
                return empty()
            m = st.matrix(tx)
            data = np.array([[m[r["species_id"]].get(s["id"], 0) for s in stations] for r in rows], dtype=float)
            im = ax.imshow(data, aspect="auto", cmap="YlGn")
            ax.set_xticks(range(len(stations)), [s["name"] for s in stations], rotation=45, ha="right")
            ax.set_yticks(range(len(rows)), [r["species"] for r in rows])
            for i in range(data.shape[0]):
                for j in range(data.shape[1]):
                    if data[i, j]:
                        ax.text(j, i, int(data[i, j]), ha="center", va="center", fontsize=7,
                                color="white" if data[i, j] > data.max() * 0.6 else theme.TEXT)
            ax.grid(False)
            self.fig.colorbar(im, ax=ax, label="Records")
            ax.set_title("Records per species and station" + title_tx)
        self.canvas.draw()

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save chart", f"{self.kind.currentText()}.png",
                                              "PNG image (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if path:
            self.fig.savefig(path, dpi=200, bbox_inches="tight")


# ---------------------------------------------------------------- dialogs
class ThresholdDialog(QDialog):
    def __init__(self, parent, project):
        super().__init__(parent)
        self.setWindowTitle("Detection settings")
        f = QFormLayout(self)
        self.a = QDoubleSpinBox()
        self.u = QDoubleSpinBox()
        for sb, v in ((self.a, project["animal_threshold"]), (self.u, project["uncertain_threshold"])):
            sb.setRange(0.01, 0.99)
            sb.setSingleStep(0.01)
            sb.setValue(v)
        self.gap = QSpinBox()
        self.gap.setRange(1, 7200)
        self.gap.setSuffix(" s")
        self.gap.setValue(project["event_gap_seconds"])
        f.addRow("Animal if detector confidence ≥", self.a)
        f.addRow("Uncertain if confidence ≥", self.u)
        info = QLabel("Below the 'uncertain' value a file counts as Empty. Lower values: fewer animals missed, "
                      "more files to check. Changes apply instantly, no need to re-run the detector.")
        info.setWordWrap(True)
        info.setObjectName("TileNote")
        f.addRow(info)
        f.addRow("Same event if files are less than", self.gap)
        g = QLabel("The event gap applies to deployments processed (or regrouped) after the change. "
                   "Use 1800 s (30 min) for the common independence rule.")
        g.setWordWrap(True)
        g.setObjectName("TileNote")
        f.addRow(g)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def accept(self):
        if self.u.value() >= self.a.value():
            QMessageBox.warning(self, "Thresholds", "The 'uncertain' value must be lower than the 'animal' value.")
            return
        super().accept()


class ShapefileDialog(QDialog):
    def __init__(self, parent, options, current=0):
        super().__init__(parent)
        self.setWindowTitle("Export shapefiles")
        f = QFormLayout(self)
        self.taxon = QComboBox()
        for label, data in options:
            self.taxon.addItem(label, data)
        self.taxon.setCurrentIndex(current)
        f.addRow("Species or group", self.taxon)
        info = QLabel("Creates two point layers (WGS84) that open in QGIS, ArcGIS and Google Earth Pro:<br>"
                      "• <b>…_stations</b>: every station, with trap-nights, records, individuals, RAI and presence (0/1)<br>"
                      "• <b>…_events</b>: one point per record, with species, date, time and count")
        info.setWordWrap(True)
        f.addRow(info)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Choose folder and export…")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


# ---------------------------------------------------------------- page
class ProjectPage(QWidget):
    changed = Signal()
    open_station = Signal(int)
    go_to_event = Signal(int, int)       # deployment id, event id
    open_deployment = Signal(int)

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.project_id = None
        self.st = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)

        top = QHBoxLayout()
        tl = QVBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        top.addLayout(tl, 1)
        top.addWidget(QLabel("Show:"))
        self.taxon = QComboBox()
        self.taxon.setMinimumWidth(220)
        self.taxon.currentIndexChanged.connect(self._taxon_changed)
        top.addWidget(self.taxon)
        b_set = QPushButton("Detection settings")
        b_set.setIcon(icon("settings"))
        b_set.clicked.connect(self._settings)
        b_xl = QPushButton("Export Excel")
        b_xl.setIcon(icon("file-spreadsheet", "#FFFFFF"))
        b_xl.setObjectName("Primary")
        b_xl.clicked.connect(self._export_excel)
        b_shp = QPushButton("Export shapefile")
        b_shp.setIcon(icon("map-2", "#FFFFFF"))
        b_shp.setObjectName("Accent")
        b_shp.clicked.connect(self._export_shp)
        for b in (b_set, b_xl, b_shp):
            top.addWidget(b)
        lay.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = {}
        specs = [
            ("stations", "Stations", "map-pin"), ("trapnights", "Trap-nights", "calendar-time"),
            ("traphours", "Trap hours", "hourglass"), ("files", "Files processed", "photo"),
            ("records", "Records", "paw"), ("richness", "Wild species", "trees"),
            ("best", "Best station", "star"), ("worst", "Lowest station", "target-arrow"),
        ]
        for i, (k, label, ic) in enumerate(specs):
            t = Tile(label, clickable=True, icon_name=ic, icon_color=theme.OCHRE if k in ("best", "records") else theme.OLIVE)
            t.setToolTip("Click for details")
            t.clicked.connect(lambda k=k: self._tile_clicked(k))
            self.tiles[k] = t
            grid.addWidget(t, 0, i)
        lay.addLayout(grid)

        self.tabs = QTabWidget()
        # map
        mw = QWidget()
        ml = QVBoxLayout(mw)
        self.map = MapWidget()
        self.map.canvas.marker_clicked.connect(lambda key: self.open_station.emit(int(key)))
        ml.addWidget(self.map, 1)
        self.map_note = QLabel()
        self.map_note.setObjectName("TileNote")
        ml.addWidget(self.map_note)
        self.tabs.addTab(mw, icon("map-2"), "Map")
        self.charts = ChartsPanel()
        self.tabs.addTab(self.charts, icon("chart-bar"), "Charts")
        self.st_table = table(["Station", "Elevation (m)", "Deployments", "Trap-nights", "Trap hours",
                               "Stopped early", "Files", "False triggers", "Records", "Wild species",
                               "Wild RAI", "Species"], stretch_last=True)
        self.st_table.cellDoubleClicked.connect(
            lambda r, _c: self.open_station.emit(self.st_table.item(r, 0).data(Qt.ItemDataRole.UserRole)))
        self.tabs.addTab(self.st_table, icon("map-pin"), "Stations")
        self.dep_table = table(["Station", "Deployment", "Start", "End", "Period from", "Trap-nights",
                                "Trap hours", "Stopped early", "Files", "Animal", "Empty"], stretch_last=True)
        self.dep_table.cellDoubleClicked.connect(
            lambda r, _c: self.open_deployment.emit(self.dep_table.item(r, 1).data(Qt.ItemDataRole.UserRole)))
        self.tabs.addTab(self.dep_table, icon("camera"), "Deployments")
        spw = QWidget()
        spl = QVBoxLayout(spw)
        spl.setContentsMargins(0, 6, 0, 0)
        sp_hint = QLabel("Click a species to see all its photos and videos.")
        sp_hint.setObjectName("TileNote")
        spl.addWidget(sp_hint)
        self.sp_table = table(["Species", "Scientific name", "Group", "Records", "Individuals", "Stations",
                               "Naive occupancy", "RAI", "First record", "Last record"], stretch_last=True)
        self.sp_table.cellClicked.connect(self._species_clicked)
        self.sp_table.setCursor(Qt.CursorShape.PointingHandCursor)
        spl.addWidget(self.sp_table)
        self.tabs.addTab(spw, icon("paw"), "Species")
        defs = QLabel("<br>".join(f"<b>{a}</b>: {b}" for a, b in export.DEFINITIONS))
        defs.setWordWrap(True)
        defs.setAlignment(Qt.AlignmentFlag.AlignTop)
        defs.setContentsMargins(14, 14, 14, 14)
        self.tabs.addTab(defs, icon("info-circle"), "How it's calculated")
        lay.addWidget(self.tabs, 1)

    # ------------------------------------------------------------ loading
    def load(self, project_id):
        self.project_id = project_id
        p = db.get_project(self.con, project_id)
        self.title.setText(p["name"])
        self.subtitle.setText(" · ".join(x for x in (p["location"], p["notes"].split("\n")[0] if p["notes"] else "") if x))
        self.st = S.project_stats(self.con, project_id)
        self._fill_taxa()
        self._refresh()

    def _fill_taxa(self):
        cur = self.taxon.currentData()
        self.taxon.blockSignals(True)
        self.taxon.clear()
        self.taxon.addItem("All species", None)
        used = {r.species_id for r in self.st.records}
        groups = sorted({self.st.species[s].get("taxon_group") for s in used if self.st.species[s].get("taxon_group")},
                        key=lambda g: TAXON_GROUPS.index(g) if g in TAXON_GROUPS else 99)
        for g in groups:
            self.taxon.addItem(f"Group: {g}", ("group", g))
        for sid in sorted(used, key=lambda s: self.st.species[s]["common_name"].lower()):
            self.taxon.addItem(self.st.species[sid]["common_name"], ("species", sid))
        i = self.taxon.findData(cur)
        self.taxon.setCurrentIndex(max(0, i))
        self.taxon.blockSignals(False)

    def taxon_options(self):
        return [(self.taxon.itemText(i), self.taxon.itemData(i)) for i in range(self.taxon.count())]

    def _taxon_label(self):
        t = self.taxon.currentText()
        return t.replace("Group: ", "")

    def _taxon_changed(self):
        self._refresh()

    def _refresh(self):
        st = self.st
        tx = self.taxon.currentData()
        rows = st.station_summary()
        files = sum(r["files"] for r in rows)
        empty = sum(r["empty_files"] for r in rows)
        early = sum(r["stopped_early"] for r in rows)
        self.tiles["stations"].set(str(len(rows)), f"{len(st.effort)} deployments")
        self.tiles["trapnights"].set(f"{st.total_trap_nights():,.0f}", f"{early} camera(s) stopped early" if early else "all cameras ran full period")
        self.tiles["traphours"].set(f"{st.total_trap_hours():,.0f}")
        self.tiles["files"].set(f"{files:,}", f"{100 * empty / files:.0f} % empty" if files else "")
        recs = st.recs(tx)
        self.tiles["records"].set(f"{len(recs):,}", self._taxon_label() if tx else "all species")
        wild = st.wild_species()
        self.tiles["richness"].set(str(len({r.species_id for r in st.records if r.species_id in wild})))
        best, worst = st.best_worst()
        self.tiles["best"].set(best["station"] if best else "–",
                               f"{best['wild_rai']:.1f} RAI · {best['richness']} species" if best else "")
        self.tiles["worst"].set(worst["station"] if worst and worst is not best else "–",
                                f"{worst['wild_rai']:.1f} RAI · {worst['richness']} species" if worst and worst is not best else "")

        # map bubbles: size by records of the selected taxon
        m = st.matrix(tx)
        per_station = {r["station_id"]: 0 for r in rows}
        for sid in m:
            for stn, n in m[sid].items():
                per_station[stn] = per_station.get(stn, 0) + n
        mx = max(per_station.values() or [0])
        markers = []
        for r in rows:
            if r["latitude"] is None:
                continue
            n = per_station.get(r["station_id"], 0)
            rad = 6 + (18 * (n / mx) ** 0.5 if mx else 0)
            markers.append({
                "lat": r["latitude"], "lon": r["longitude"], "key": r["station_id"],
                "label": f"{r['station']} ({n})" if n else r["station"],
                "colour": theme.OCHRE if n else "#9A9486", "radius": rad, "alpha": 210,
                "tooltip": f"{r['station']}\n{n} records ({self._taxon_label()})\n"
                           f"{r['trap_nights']:.0f} trap-nights · {r['richness']} wild species"
                           + (f"\nElevation {r['elevation']:.0f} m" if r["elevation"] is not None else ""),
            })
        self.map.canvas.set_markers(markers, fit=True)
        no_gps = [r["station"] for r in rows if r["latitude"] is None]
        self.map_note.setText(
            f"Circle size = records of {self._taxon_label().lower() if tx else 'all species'}; grey = none recorded. "
            "Click a station to open it."
            + (f"  ·  No GPS yet: {', '.join(no_gps)}" if no_gps else ""))

        fill(self.st_table, [[
            self._id_item(r["station"], r["station_id"]), NumItem(r["elevation"], 0), NumItem(r["deployments"]),
            NumItem(r["trap_nights"]), NumItem(r["trap_hours"], 0), NumItem(r["stopped_early"]), NumItem(r["files"]),
            NumItem(r["false_trigger_rate"], pct=True), NumItem(r["records"]), NumItem(r["richness"]),
            NumItem(r["wild_rai"], 2), ", ".join(r["species"]),
        ] for r in rows])
        stn = {r["station_id"]: r["station"] for r in rows}
        dep_rows = []
        for e in sorted(st.effort, key=lambda e: (stn.get(e.station_id, ""), e.start or 0)):
            dep = self.con.execute("SELECT * FROM deployment WHERE id=?", (e.deployment_id,)).fetchone()
            c = {}
            if dep:
                from ctt import labels as L

                c = L.group_counts(self.con, e.deployment_id, st.project["animal_threshold"], st.project["uncertain_threshold"])
            src = "files" if dep is None or dep["dates_auto"] else "dates typed in"
            dep_rows.append([
                stn.get(e.station_id, ""), self._id_item(e.name, e.deployment_id),
                e.start.strftime("%Y-%m-%d %H:%M") if e.start else "", e.stop.strftime("%Y-%m-%d %H:%M") if e.stop else "",
                src, NumItem(e.trap_nights), NumItem(e.trap_hours, 0), "yes" if e.stopped_early else "",
                NumItem(sum(c.values())), NumItem(c.get("animal", 0)), NumItem(c.get("empty", 0)),
            ])
        fill(self.dep_table, dep_rows)
        fill(self.sp_table, [[
            self._id_item(r["species"], r["species_id"]), r["scientific_name"], r["group"], NumItem(r["records"]), NumItem(r["individuals"]),
            NumItem(r["stations"]), NumItem(r["naive_occupancy"], 2), NumItem(r["rai"], 2),
            r["first"].strftime("%Y-%m-%d") if r["first"] else "", r["last"].strftime("%Y-%m-%d") if r["last"] else "",
        ] for r in st.species_summary(tx)])
        self.charts.set_data(st, tx, self._taxon_label())

    @staticmethod
    def _id_item(text, rid):
        it = QTableWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, rid)
        return it

    # ------------------------------------------------------------ clicks
    def _tab(self, name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)

    def _tile_clicked(self, key):
        if key in ("best", "worst"):
            b, w = self.st.best_worst() if self.st else (None, None)
            row = b if key == "best" else w
            if row and not (key == "worst" and row is b):
                self.open_station.emit(row["station_id"])
            return
        target = {"stations": "Stations", "trapnights": "Deployments", "traphours": "Deployments",
                  "files": "Deployments", "records": "Species", "richness": "Species"}.get(key)
        if target:
            self._tab(target)

    def _species_clicked(self, row, _col):
        it = self.sp_table.item(row, 0)
        if it is None:
            return
        from .gallery import FootageGallery

        dlg = FootageGallery(self, self.con, self.project_id, it.text(), {it.text()})
        dlg.go_to_event.connect(self.go_to_event)
        dlg.exec()

    # ------------------------------------------------------------ actions
    def _settings(self):
        p = db.get_project(self.con, self.project_id)
        dlg = ThresholdDialog(self, p)
        if dlg.exec():
            db.update_project(self.con, self.project_id, animal_threshold=dlg.a.value(),
                              uncertain_threshold=dlg.u.value(), event_gap_seconds=dlg.gap.value())
            self.load(self.project_id)
            self.changed.emit()

    def _export_excel(self):
        p = db.get_project(self.con, self.project_id)
        path, _ = QFileDialog.getSaveFileName(self, "Export to Excel", f"{p['name']} camera traps.xlsx",
                                              "Excel (*.xlsx);;CSV, observations only (*.csv)")
        if not path:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Include empty files?")
        box.setText("Include rows for empty files in the Observations sheet?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        include_empty = box.exec() == QMessageBox.StandardButton.Yes
        try:
            n = export.export_project(self.con, self.project_id, path, include_empty)
        except PermissionError:
            QMessageBox.critical(self, "Export failed", "The file is open in another program (Excel?). Close it and try again.")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        from .util import open_file

        if QMessageBox.question(self, "Exported", f"{n} observation rows written to\n{path}\n\nOpen the file now?") \
                == QMessageBox.StandardButton.Yes:
            open_file(path)

    def _export_shp(self):
        opts = self.taxon_options()
        dlg = ShapefileDialog(self, opts, self.taxon.currentIndex())
        if not dlg.exec():
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the shapefiles")
        if not folder:
            return
        label = dlg.taxon.currentText().replace("Group: ", "")
        try:
            res = export.export_shapefiles(self.con, self.project_id, folder, dlg.taxon.currentData(), label)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        msg = (f"Written to {res['folder']}:\n• {res['name']}_stations.shp ({res['stations']} stations)\n"
               f"• {res['name']}_events.shp ({res['events']} records)")
        if res["no_gps"]:
            msg += "\n\nSkipped (no GPS): " + ", ".join(res["no_gps"])
        QMessageBox.information(self, "Shapefiles exported", msg)
