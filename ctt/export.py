"""Export labelled data to CSV or Excel (one row per file x species)."""

from __future__ import annotations

import csv
from pathlib import Path

from .grouping import classify, GROUP_LABELS
from .processing import corrected_time

COLUMNS = [
    "project", "station", "latitude", "longitude", "deployment", "camera",
    "file", "file_type", "date", "time", "event_id", "detection_group",
    "species", "scientific_name", "count", "label_note", "event_note",
    "animal_score", "person_score", "vehicle_score",
]


def export_rows(con, project_id, include_empty=False):
    proj = con.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()
    a_thr, u_thr = proj["animal_threshold"], proj["uncertain_threshold"]
    media = con.execute(
        """SELECT m.*, d.name dep_name, d.camera, d.folder, d.time_offset_seconds,
                  s.name st_name, s.latitude, s.longitude, e.note event_note
           FROM media m
           JOIN deployment d ON d.id=m.deployment_id
           JOIN station s ON s.id=d.station_id
           LEFT JOIN event e ON e.id=m.event_id
           WHERE s.project_id=?
           ORDER BY s.name, d.name, m.taken_at, m.relpath""",
        (project_id,),
    ).fetchall()
    # preload labels
    ev_labels, md_labels = {}, {}
    for l in con.execute(
        """SELECT l.*, sp.common_name, sp.scientific_name FROM label l
           JOIN species sp ON sp.id=l.species_id
           JOIN event e ON e.id=l.event_id JOIN deployment d ON d.id=e.deployment_id
           JOIN station s ON s.id=d.station_id WHERE s.project_id=?""",
        (project_id,),
    ):
        target = md_labels.setdefault(l["media_id"], []) if l["media_id"] else ev_labels.setdefault(l["event_id"], [])
        target.append(l)

    for m in media:
        grp = classify(m["max_animal"], m["max_person"], m["max_vehicle"], a_thr, u_thr, m["manual_group"])
        if grp == "empty" and not include_empty:
            continue
        ts = corrected_time(m["taken_at"], m["time_offset_seconds"])
        base = {
            "project": proj["name"],
            "station": m["st_name"],
            "latitude": m["latitude"],
            "longitude": m["longitude"],
            "deployment": m["dep_name"],
            "camera": m["camera"],
            "file": str(Path(m["folder"]) / m["relpath"]),
            "file_type": m["kind"],
            "date": ts.date().isoformat() if ts else "",
            "time": ts.time().isoformat() if ts else "",
            "event_id": m["event_id"],
            "detection_group": GROUP_LABELS.get(grp, "Not processed") if grp else "Not processed",
            "event_note": m["event_note"] or "",
            "animal_score": _r(m["max_animal"]),
            "person_score": _r(m["max_person"]),
            "vehicle_score": _r(m["max_vehicle"]),
        }
        labels = md_labels.get(m["id"]) or ev_labels.get(m["event_id"]) or []
        if not labels:
            yield {**base, "species": "", "scientific_name": "", "count": "", "label_note": ""}
        for l in labels:
            yield {
                **base,
                "species": l["common_name"],
                "scientific_name": l["scientific_name"],
                "count": l["count"],
                "label_note": l["note"],
            }


def _r(v):
    return "" if v is None else round(float(v), 3)


def export_project(con, project_id, path, include_empty=False) -> int:
    """Excel: several sheets (observations + statistics). CSV: observations only."""
    path = Path(path)
    rows = list(export_rows(con, project_id, include_empty))
    if path.suffix.lower() == ".xlsx":
        _write_excel(con, project_id, path, rows)
    else:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
    return len(rows)


DEFINITIONS = [
    ("Record", "One labelled event (photos/videos closer in time than the project's event gap) at one station, per species."),
    ("Trap period", "Deployment start date 00:00 to end date 24:00. If the last file is >24 h before the end date the camera probably stopped early; the period then ends at the last file (column 'stopped_early')."),
    ("Trap-nights", "Trap hours / 24."),
    ("RAI", "Relative abundance index = records / trap-nights x 100."),
    ("Naive occupancy", "Stations with at least one record / stations with trap effort. Not corrected for detection probability."),
    ("Species richness", "Number of wild species recorded (taxon groups Domestic and Human excluded)."),
    ("False-trigger rate", "Files with no animal, person or vehicle / processed files."),
    ("Detection groups", "Animal, Uncertain, Human/Vehicle, Empty: from MegaDetector v5a scores and the project thresholds, or set by hand."),
]


def _write_excel(con, project_id, path, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from . import stats as S

    st = S.project_stats(con, project_id)
    head_fill = PatternFill("solid", fgColor="4F5D2F")
    head_font = Font(color="FFFFFF", bold=True)

    wb = Workbook()

    def sheet(title, header, data, first=False):
        ws = wb.active if first else wb.create_sheet(title)
        ws.title = title
        ws.append(header)
        for c in ws[1]:
            c.fill, c.font = head_fill, head_font
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for r in data:
            ws.append([_cell(v) for v in r])
        ws.freeze_panes = "B2"
        for i, h in enumerate(header, 1):
            width = max([len(str(h))] + [len(str(_cell(r[i - 1]) or "")) for r in data[:500]]) + 2
            ws.column_dimensions[get_column_letter(i)].width = min(50, max(9, width))
        return ws

    sheet("Observations", COLUMNS, [[r.get(c, "") for c in COLUMNS] for r in rows], first=True)

    srows = st.station_summary()
    sheet("Stations", ["Station", "Latitude", "Longitude", "Elevation (m)", "Deployments", "Trap-nights",
                       "Trap hours", "Deployments stopped early", "Files", "Empty files", "False-trigger rate (%)",
                       "Records (all)", "Wild records", "Species richness", "Wild RAI", "Species"],
          [[r["station"], r["latitude"], r["longitude"], r["elevation"], r["deployments"], _r1(r["trap_nights"]),
            _r1(r["trap_hours"]), r["stopped_early"], r["files"], r["empty_files"], _pct(r["false_trigger_rate"]),
            r["records"], r["wild_records"], r["richness"], _r1(r["wild_rai"]), ", ".join(r["species"])] for r in srows])

    sp = st.species_summary()
    sheet("Species", ["Species", "Scientific name", "Taxon group", "Records", "Individuals (sum of counts)",
                      "Stations", "Naive occupancy", "RAI (project)", "First record", "Last record"],
          [[r["species"], r["scientific_name"], r["group"], r["records"], r["individuals"], r["stations"],
            _r1(r["naive_occupancy"], 3), _r1(r["rai"], 2), r["first"], r["last"]] for r in sp])

    names = [s["name"] for s in st.stations]
    ids = [s["id"] for s in st.stations]
    m, rai = st.matrix(), st.rai()
    order = [r["species_id"] for r in sp]
    sheet("Records per station", ["Species"] + names,
          [[st.species[i]["common_name"]] + [m[i].get(s, 0) for s in ids] for i in order])
    sheet("RAI per station", ["Species"] + names,
          [[st.species[i]["common_name"]] + [_r1(rai.get(i, {}).get(s), 2) if m[i].get(s) else 0 for s in ids] for i in order])

    stn = {s["id"]: s["name"] for s in st.stations}
    sheet("Deployments", ["Station", "Deployment", "Trap start", "Trap end used", "Planned end", "First file",
                          "Last file", "Stopped early", "Trap hours", "Trap-nights"],
          [[stn.get(e.station_id), e.name, e.start, e.stop, e.nominal_stop, e.first_file, e.last_file,
            "yes" if e.stopped_early else "", _r1(e.trap_hours), _r1(e.trap_nights)] for e in st.effort])

    sheet("Definitions", ["Term", "Meaning"], [list(d) for d in DEFINITIONS])
    wb.save(path)


def _cell(v):
    return v


def _r1(v, d=1):
    return None if v is None else round(float(v), d)


def _pct(v):
    return None if v is None else round(100 * v, 1)


# ---------------------------------------------------------------- shapefiles
def export_shapefiles(con, project_id, folder, taxon=None, taxon_label="all species") -> dict:
    """Two point shapefiles for a species, taxon group or all species:
    <name>_stations.shp (one point per station, with effort and RAI) and
    <name>_events.shp (one point per record)."""
    from . import shapefile as SHP
    from . import stats as S

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    st = S.project_stats(con, project_id)
    keep = st.species_in(taxon)
    safe = "".join(c if c.isalnum() else "_" for c in taxon_label).strip("_") or "taxon"
    eff = st.station_effort()
    stations = {s["id"]: s for s in st.stations}

    srows = []
    for s in st.stations:
        recs = [r for r in st.records if r.station_id == s["id"] and r.species_id in keep]
        tn = eff[s["id"]]["trap_nights"]
        whens = [r.when for r in recs if r.when]
        srows.append({
            "station": s["name"], "latitude": s["latitude"], "longitude": s["longitude"],
            "elevation": s.get("elevation"), "taxon": taxon_label, "trapnights": round(tn, 2),
            "records": len(recs), "individ": sum(r.count for r in recs),
            "rai": round(len(recs) / tn * 100, 3) if tn else None,
            "present": 1 if recs else 0,
            "species": ", ".join(sorted({st.species[r.species_id]["common_name"] for r in recs})),
            "first": min(whens).date() if whens else None, "last": max(whens).date() if whens else None,
        })
    n1 = SHP.write_points(folder / f"{safe}_stations", [
        ("station", "C"), ("taxon", "C"), ("elevation", "F"), ("trapnights", "F"), ("records", "N"),
        ("individ", "N"), ("rai", "F"), ("present", "N"), ("species", "C"), ("first", "D"), ("last", "D"),
    ], srows)

    erows = []
    for r in sorted((r for r in st.records if r.species_id in keep), key=lambda r: (r.station_id, r.when or 0)):
        s = stations[r.station_id]
        sp = st.species[r.species_id]
        erows.append({
            "station": s["name"], "latitude": s["latitude"], "longitude": s["longitude"],
            "species": sp["common_name"], "sciname": sp.get("scientific_name") or "",
            "group": sp.get("taxon_group") or "", "date": r.when.date() if r.when else None,
            "time": f"{r.when:%H:%M}" if r.when else "", "count": r.count, "event_id": r.event_id,
        })
    n2 = SHP.write_points(folder / f"{safe}_events", [
        ("station", "C"), ("species", "C"), ("sciname", "C"), ("group", "C"), ("date", "D"),
        ("time", "C"), ("count", "N"), ("event_id", "N"),
    ], erows)
    missing = [s["name"] for s in st.stations if s["latitude"] is None]
    return {"stations": n1, "events": n2, "folder": str(folder), "name": safe, "no_gps": missing}
