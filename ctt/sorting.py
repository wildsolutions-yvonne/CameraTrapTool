"""Copy a deployment's files into subfolders: Wildlife / People & livestock / Empty / Uncertain.

Originals are never moved. Copies go to <deployment folder>/CTT_Sorted/<group>/<original sub-path>.
The CTT_Sorted folder is ignored when the deployment is scanned again.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .db import DOMESTIC_GROUPS
from .grouping import classify

SORTED_DIR = "CTT_Sorted"
WILDLIFE = "Wildlife"
PEOPLE = "People & livestock"
EMPTY = "Empty"
UNCERTAIN = "Uncertain"
FOLDERS = [WILDLIFE, PEOPLE, EMPTY, UNCERTAIN]


def destination_group(detector_group, label_groups: set) -> str | None:
    """Decide the subfolder for one file.

    Labels win over the detector: a file labelled with a Domestic/Human species goes to
    People & livestock, a file labelled with any wild species goes to Wildlife.
    """
    if label_groups:
        if label_groups & DOMESTIC_GROUPS and not (label_groups - DOMESTIC_GROUPS):
            return PEOPLE
        if label_groups - DOMESTIC_GROUPS:
            return WILDLIFE
    return {
        "animal": WILDLIFE,
        "human": PEOPLE,
        "empty": EMPTY,
        "uncertain": UNCERTAIN,
    }.get(detector_group)


def plan(con, deployment_id):
    """[(relpath, kind, folder)] for every processed file of the deployment."""
    dep = con.execute(
        "SELECT d.*, s.project_id FROM deployment d JOIN station s ON s.id=d.station_id WHERE d.id=?",
        (deployment_id,),
    ).fetchone()
    p = con.execute("SELECT * FROM project WHERE id=?", (dep["project_id"],)).fetchone()
    # taxon groups of the labels that apply to each file (own override, else event labels)
    ev_groups, md_groups = {}, {}
    for r in con.execute(
        """SELECT l.event_id, l.media_id, IFNULL(s.taxon_group,'') g FROM label l
           JOIN species s ON s.id=l.species_id JOIN event e ON e.id=l.event_id
           WHERE e.deployment_id=?""",
        (deployment_id,),
    ):
        target = md_groups.setdefault(r["media_id"], set()) if r["media_id"] else ev_groups.setdefault(r["event_id"], set())
        target.add(r["g"] or "Other")
    out = []
    for m in con.execute("SELECT * FROM media WHERE deployment_id=? ORDER BY relpath", (deployment_id,)):
        g = classify(m["max_animal"], m["max_person"], m["max_vehicle"],
                     p["animal_threshold"], p["uncertain_threshold"], m["manual_group"])
        groups = md_groups.get(m["id"]) or ev_groups.get(m["event_id"]) or set()
        folder = destination_group(g, groups)
        if folder:
            out.append((m["relpath"], m["kind"], folder))
    return Path(dep["folder"]), out


def copy_sorted(con, deployment_id, dest: str | Path | None = None, progress=None, should_stop=None) -> dict:
    src_root, items = plan(con, deployment_id)
    dest = Path(dest) if dest else src_root / SORTED_DIR
    counts = {f: 0 for f in FOLDERS}
    skipped = 0
    for i, (rel, _kind, folder) in enumerate(items, 1):
        if should_stop and should_stop():
            break
        src = src_root / rel
        dst = dest / folder / rel
        if dst.exists() and src.exists() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        counts[folder] += 1
        if progress:
            progress(i, len(items), rel)
    return {"counts": counts, "skipped": skipped, "dest": str(dest), "total": len(items)}
