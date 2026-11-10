"""Finding all footage of a species in a project."""

from __future__ import annotations

from . import labels
from .processing import corrected_time


def species_footage(con, project_id, names: set):
    """Files in the project labelled with any of the given species names, in time order."""
    p = con.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()
    deps = con.execute(
        """SELECT d.*, s.name station FROM deployment d JOIN station s ON s.id=d.station_id
           WHERE s.project_id=?""",
        (project_id,),
    ).fetchall()
    depmap = {d["id"]: d for d in deps}
    fl = labels.file_labels(con, list(depmap), p["animal_threshold"], p["uncertain_threshold"])
    out = []
    for m in con.execute(
        f"SELECT * FROM media WHERE deployment_id IN ({','.join('?' * len(depmap)) or 'NULL'})", list(depmap)
    ):
        lab = fl.get(m["id"], {}).get("labels", [])
        if any(c in names for c, *_ in lab):
            d = depmap[m["deployment_id"]]
            out.append({
                "media": m, "station": d["station"], "deployment": d["name"], "folder": d["folder"],
                "when": corrected_time(m["taken_at"], d["time_offset_seconds"]),
                "labels": labels.label_text(lab),
            })
    out.sort(key=lambda r: (r["when"] is None, r["when"] or 0, r["media"]["relpath"]))
    return out
