"""Copy a deployment's files into subfolders:
Wildlife / People & livestock / Survey team / Empty / Uncertain.

- Originals are never moved or changed.
- Copies go to <deployment folder>/Trapster_Sorted/<folder>/<original sub-path>, or to a
  folder you choose. Labelled files get the species in the file name:
  IMG_0042 - Patas monkey x3.JPG
- Running it again brings the folders up to date: copies that no longer match their
  label (e.g. after relabelling) are removed, so a file is never in two folders.
- Sorted folders are ignored when the deployment is scanned again.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .db import DOMESTIC_GROUPS
from .labels import file_labels

SORTED_DIR = "Trapster_Sorted"
SKIP_DIRS = {"Trapster_Sorted", "CTT_Sorted"}   # CTT_Sorted = older versions
MANIFEST = ".trapster_copies.json"
WILDLIFE = "Wildlife"
PEOPLE = "People & livestock"
TEAM = "Survey team"
EMPTY = "Empty"
UNCERTAIN = "Uncertain"
FOLDERS = [WILDLIFE, PEOPLE, TEAM, EMPTY, UNCERTAIN]


def destination_folder(group, labels) -> str | None:
    """Decide the subfolder for one file.

    Quick labels given by hand win; then species labels (wild species -> Wildlife,
    only Domestic/Human species -> People & livestock); then the detector.
    """
    if group == "team":
        return TEAM
    if labels:
        groups = {g or "" for _c, _s, g, _n, _note in labels}
        if groups - DOMESTIC_GROUPS:
            return WILDLIFE
        return PEOPLE
    return {"animal": WILDLIFE, "human": PEOPLE, "empty": EMPTY, "uncertain": UNCERTAIN}.get(group)


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def labelled_name(relpath: str, labels) -> str:
    """'DCIM/IMG_0042.JPG' + labels -> 'DCIM/IMG_0042 - Patas monkey x3, Olive baboon.JPG'"""
    if not labels:
        return relpath
    p = Path(relpath)
    tag = ", ".join(f"{c} x{n}" if n and n > 1 else c for c, _s, _g, n, _note in labels)
    tag = _BAD.sub("", tag).strip().rstrip(".")[:120]
    return str(p.with_name(f"{p.stem} - {tag}{p.suffix}")).replace("\\", "/")


def plan(con, deployment_id):
    """(source folder, [(relpath, kind, folder, new relative name)], species without a taxon group)"""
    dep = con.execute(
        "SELECT d.*, s.project_id FROM deployment d JOIN station s ON s.id=d.station_id WHERE d.id=?",
        (deployment_id,),
    ).fetchone()
    p = con.execute("SELECT * FROM project WHERE id=?", (dep["project_id"],)).fetchone()
    fl = file_labels(con, [deployment_id], p["animal_threshold"], p["uncertain_threshold"])
    out, no_group = [], set()
    for m in con.execute("SELECT * FROM media WHERE deployment_id=? ORDER BY relpath", (deployment_id,)):
        info = fl.get(m["id"])
        if not info or info["group"] is None:
            continue  # not processed yet
        labels = info["labels"]
        no_group |= {c for c, _s, g, _n, _note in labels if not g}
        folder = destination_folder(info["group"], labels)
        if folder:
            out.append((m["relpath"], m["kind"], folder, labelled_name(m["relpath"], labels)))
    return Path(dep["folder"]), out, sorted(no_group)


def copy_sorted(con, deployment_id, dest: str | Path | None = None, progress=None, should_stop=None) -> dict:
    src_root, items, no_group = plan(con, deployment_id)
    dest = Path(dest) if dest else src_root / SORTED_DIR
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / MANIFEST
    try:
        old = set(json.loads(manifest_path.read_text(encoding="utf-8")).get("files", []))
    except (OSError, ValueError):
        old = set()

    wanted = {f"{folder}/{new}" for _rel, _k, folder, new in items}
    removed = 0
    for rel in sorted(old - wanted):  # copies that no longer match their label
        f = dest / rel
        try:
            if f.is_file():
                f.unlink()
                removed += 1
            parent = f.parent
            while parent != dest and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except OSError:
            pass

    counts = {f: 0 for f in FOLDERS}
    skipped = copied = 0
    missing = []
    for i, (rel, _kind, folder, new) in enumerate(items, 1):
        if should_stop and should_stop():
            break
        src = src_root / rel
        dst = dest / folder / new
        if not src.exists():
            missing.append(rel)
        elif dst.exists() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        counts[folder] += 1
        if progress:
            progress(i, len(items), rel)
    manifest_path.write_text(json.dumps({"deployment_id": deployment_id, "files": sorted(wanted)}, indent=0),
                             encoding="utf-8")
    return {"counts": counts, "copied": copied, "skipped": skipped, "removed": removed,
            "missing": missing, "dest": str(dest), "total": len(items), "no_group": no_group}
