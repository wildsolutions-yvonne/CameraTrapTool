"""Reading and writing manual species labels."""

from __future__ import annotations

from .grouping import sql_group_expr


def event_labels(con, event_id):
    return con.execute(
        "SELECT l.*, s.common_name, s.scientific_name FROM label l JOIN species s ON s.id=l.species_id"
        " WHERE l.event_id=? AND l.media_id IS NULL ORDER BY s.common_name",
        (event_id,),
    ).fetchall()


def media_labels(con, media_id):
    return con.execute(
        "SELECT l.*, s.common_name, s.scientific_name FROM label l JOIN species s ON s.id=l.species_id"
        " WHERE l.media_id=? ORDER BY s.common_name",
        (media_id,),
    ).fetchall()


def effective_labels(con, media_id):
    """Labels that apply to one file: its own override if any, else its event's labels."""
    own = media_labels(con, media_id)
    if own:
        return own
    ev = con.execute("SELECT event_id FROM media WHERE id=?", (media_id,)).fetchone()
    return event_labels(con, ev["event_id"]) if ev and ev["event_id"] else []


def set_event_labels(con, event_id, entries, note=None):
    """entries: list of (species_id, count, note). Replaces the event-level labels."""
    con.execute("DELETE FROM label WHERE event_id=? AND media_id IS NULL", (event_id,))
    for species_id, count, lnote in entries:
        con.execute(
            "INSERT INTO label(event_id, media_id, species_id, count, note) VALUES (?,?,?,?,?)",
            (event_id, None, species_id, int(count), lnote or ""),
        )
    if note is not None:
        con.execute("UPDATE event SET note=? WHERE id=?", (note, event_id))
    con.commit()


def set_media_labels(con, media_id, entries):
    """Per-file override. Empty entries removes the override (file follows its event again)."""
    ev = con.execute("SELECT event_id FROM media WHERE id=?", (media_id,)).fetchone()["event_id"]
    con.execute("DELETE FROM label WHERE media_id=?", (media_id,))
    for species_id, count, lnote in entries:
        con.execute(
            "INSERT INTO label(event_id, media_id, species_id, count, note) VALUES (?,?,?,?,?)",
            (ev, media_id, species_id, int(count), lnote or ""),
        )
    con.commit()


def set_manual_group(con, media_ids, group):
    """Override the detector, e.g. mark an 'Empty' file as 'animal'. group=None resets."""
    con.executemany("UPDATE media SET manual_group=? WHERE id=?", [(group, i) for i in media_ids])
    con.commit()


def media_in_group(con, deployment_id, group, animal_thr, uncertain_thr):
    expr = sql_group_expr(animal_thr, uncertain_thr)
    return con.execute(
        f"SELECT m.*, {expr} AS grp FROM media m WHERE m.deployment_id=? AND {expr}=? ORDER BY m.taken_at, m.relpath",
        (deployment_id, group),
    ).fetchall()


def group_counts(con, deployment_id, animal_thr, uncertain_thr) -> dict:
    expr = sql_group_expr(animal_thr, uncertain_thr)
    rows = con.execute(
        f"SELECT {expr} AS grp, COUNT(*) n FROM media m WHERE m.deployment_id=? GROUP BY grp",
        (deployment_id,),
    ).fetchall()
    return {(r["grp"] or "pending"): r["n"] for r in rows}


def events_to_label(con, deployment_id, animal_thr, uncertain_thr, include_uncertain=True):
    """Events containing at least one non-empty file, in time order, with label status."""
    expr = sql_group_expr(animal_thr, uncertain_thr)
    groups = "('animal','human','uncertain')" if include_uncertain else "('animal','human')"
    return con.execute(
        f"""SELECT e.*,
               (SELECT COUNT(*) FROM media m WHERE m.event_id=e.id) AS n_files,
               (SELECT COUNT(*) FROM label l WHERE l.event_id=e.id) AS n_labels
            FROM event e
            WHERE e.deployment_id=?
              AND EXISTS (SELECT 1 FROM media m WHERE m.event_id=e.id AND {expr} IN {groups})
            ORDER BY e.start_at, e.id""",
        (deployment_id,),
    ).fetchall()


def event_media(con, event_id, animal_thr, uncertain_thr):
    expr = sql_group_expr(animal_thr, uncertain_thr)
    return con.execute(
        f"SELECT m.*, {expr} AS grp FROM media m WHERE m.event_id=? ORDER BY m.taken_at, m.relpath",
        (event_id,),
    ).fetchall()
