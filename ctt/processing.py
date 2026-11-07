"""Running the detector over a deployment folder and grouping files into events."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable

from . import media as M
from .detector import max_scores


def scan_deployment(con, deployment_id: int) -> int:
    """Register all media files in the deployment folder. Returns number of new files."""
    dep = con.execute("SELECT folder FROM deployment WHERE id=?", (deployment_id,)).fetchone()
    folder = Path(dep["folder"])
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    existing = {r[0] for r in con.execute("SELECT relpath FROM media WHERE deployment_id=?", (deployment_id,))}
    new = 0
    for rel, kind in M.find_media(folder):
        if rel in existing:
            continue
        full = folder / rel
        stamp = M.image_timestamp(full) if kind == "image" else M.video_timestamp(full)
        con.execute(
            "INSERT INTO media(deployment_id, relpath, kind, taken_at) VALUES (?,?,?,?)",
            (deployment_id, rel, kind, stamp.isoformat(sep=" ") if stamp else None),
        )
        new += 1
    con.commit()
    return new


def run_detection(
    con,
    deployment_id: int,
    detector,
    progress: Callable[[int, int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    video_every_seconds: float = 1.0,
) -> dict:
    """Run MegaDetector on every not-yet-processed file of a deployment.

    Safe to stop and resume: finished files are stored immediately.
    """
    dep = con.execute("SELECT folder FROM deployment WHERE id=?", (deployment_id,)).fetchone()
    folder = Path(dep["folder"])
    todo = con.execute(
        "SELECT id, relpath, kind FROM media WHERE deployment_id=? AND max_animal IS NULL AND error IS NULL"
        " ORDER BY relpath",
        (deployment_id,),
    ).fetchall()
    total = len(todo)
    done = errors = 0
    for row in todo:
        if should_stop and should_stop():
            break
        path = folder / row["relpath"]
        try:
            if row["kind"] == "image":
                scores = max_scores(detector.detect(M.read_image_bgr(path)))
                best_t = None
            else:
                scores, best_t = _scan_video(detector, path, video_every_seconds)
            con.execute(
                "UPDATE media SET max_animal=?, max_person=?, max_vehicle=?, best_frame_seconds=? WHERE id=?",
                (scores["animal"], scores["person"], scores["vehicle"], best_t, row["id"]),
            )
        except Exception as exc:  # unreadable/corrupt file: record and continue
            errors += 1
            con.execute("UPDATE media SET error=? WHERE id=?", (str(exc)[:500], row["id"]))
        done += 1
        if done % 10 == 0:
            con.commit()
        if progress:
            progress(done, total, row["relpath"])
    con.commit()
    remaining = con.execute(
        "SELECT COUNT(*) FROM media WHERE deployment_id=? AND max_animal IS NULL AND error IS NULL",
        (deployment_id,),
    ).fetchone()[0]
    if remaining == 0:
        con.execute(
            "UPDATE deployment SET processed_at=? WHERE id=?",
            (dt.datetime.now().isoformat(sep=" ", timespec="seconds"), deployment_id),
        )
        con.commit()
    return {"processed": done, "errors": errors, "remaining": remaining}


def _scan_video(detector, path, every_seconds):
    best = {"animal": 0.0, "person": 0.0, "vehicle": 0.0}
    best_t = 0.0
    any_frame = False
    for t, frame in M.sample_video_frames(path, every_seconds):
        any_frame = True
        s = max_scores(detector.detect(frame))
        if s["animal"] > best["animal"]:
            best_t = t
        for k in best:
            best[k] = max(best[k], s[k])
        if best["animal"] >= 0.8:  # clearly an animal: no need to scan the rest
            break
    if not any_frame:
        raise IOError("No frames could be read from video")
    return best, best_t


# ---------------------------------------------------------------- events
def parse_ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def build_events(con, deployment_id: int, gap_seconds: int = 60, force: bool = False) -> int:
    """Group the deployment's files into events (bursts).

    A new event starts when the time since the previous file exceeds gap_seconds.
    Files without a timestamp each become their own event. Will not rebuild if
    labels already exist unless force=True (which deletes those labels).
    """
    has_labels = con.execute(
        "SELECT COUNT(*) FROM label l JOIN event e ON e.id=l.event_id WHERE e.deployment_id=?",
        (deployment_id,),
    ).fetchone()[0]
    if has_labels and not force:
        raise RuntimeError("This deployment already has labels; events were not rebuilt.")
    con.execute("UPDATE media SET event_id=NULL WHERE deployment_id=?", (deployment_id,))
    con.execute("DELETE FROM event WHERE deployment_id=?", (deployment_id,))
    rows = con.execute(
        "SELECT id, taken_at, relpath FROM media WHERE deployment_id=?", (deployment_id,)
    ).fetchall()
    rows = sorted(rows, key=lambda r: (parse_ts(r["taken_at"]) or dt.datetime.max, r["relpath"]))
    n_events = 0
    current_id = None
    last_ts = None
    for r in rows:
        ts = parse_ts(r["taken_at"])
        new_event = (
            current_id is None
            or ts is None
            or last_ts is None
            or (ts - last_ts).total_seconds() > gap_seconds
        )
        if new_event:
            cur = con.execute(
                "INSERT INTO event(deployment_id, start_at, end_at) VALUES (?,?,?)",
                (deployment_id, r["taken_at"], r["taken_at"]),
            )
            current_id = cur.lastrowid
            n_events += 1
        else:
            con.execute("UPDATE event SET end_at=? WHERE id=?", (r["taken_at"], current_id))
        con.execute("UPDATE media SET event_id=? WHERE id=?", (current_id, r["id"]))
        last_ts = ts
    con.commit()
    return n_events


def corrected_time(taken_at, offset_seconds: int) -> dt.datetime | None:
    ts = parse_ts(taken_at)
    if ts is None:
        return None
    return ts + dt.timedelta(seconds=offset_seconds or 0)


def offset_from_example(wrong: dt.datetime, right: dt.datetime) -> int:
    """Time-correction helper: user picks one photo, says its true time."""
    return int((right - wrong).total_seconds())
