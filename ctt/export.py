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
    path = Path(path)
    rows = list(export_rows(con, project_id, include_empty))
    if path.suffix.lower() == ".xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "observations"
        ws.append(COLUMNS)
        for r in rows:
            ws.append([r.get(c, "") for c in COLUMNS])
        ws.freeze_panes = "A2"
        wb.save(path)
    else:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
    return len(rows)
