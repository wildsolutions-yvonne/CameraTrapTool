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
    _touch(con, entries)


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
    _touch(con, entries)


def _touch(con, entries):
    from .db import touch_species

    if entries:
        touch_species(con, [e[0] for e in entries])


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


# Files shown for labelling: detected animal / uncertain / people, and not given a quick
# label (Empty, People & livestock, Survey team) by hand.
_LABELLABLE = "m.manual_group IS NULL OR m.manual_group='animal'"


def events_to_label(con, deployment_id, animal_thr, uncertain_thr, include_uncertain=True):
    """Events that still contain files to label, in time order, with label status.
    Files that got a quick label (Empty, People & livestock, Survey team) are left out."""
    expr = sql_group_expr(animal_thr, uncertain_thr)
    groups = "('animal','human','uncertain')" if include_uncertain else "('animal','human')"
    cond = f"m.event_id=e.id AND ({_LABELLABLE}) AND {expr} IN {groups}"
    return con.execute(
        f"""SELECT e.*,
               (SELECT COUNT(*) FROM media m WHERE {cond}) AS n_files,
               (SELECT COUNT(*) FROM label l WHERE l.event_id=e.id) AS n_labels
            FROM event e
            WHERE e.deployment_id=? AND EXISTS (SELECT 1 FROM media m WHERE {cond})
            ORDER BY e.start_at, e.id""",
        (deployment_id,),
    ).fetchall()


def event_media(con, event_id, animal_thr, uncertain_thr, only_labellable=True):
    expr = sql_group_expr(animal_thr, uncertain_thr)
    extra = f" AND ({_LABELLABLE}) AND {expr} IN ('animal','human','uncertain')" if only_labellable else ""
    return con.execute(
        f"SELECT m.*, {expr} AS grp FROM media m WHERE m.event_id=?{extra} ORDER BY m.taken_at, m.relpath",
        (event_id,),
    ).fetchall()


def quick_label(con, media_ids, group):
    """Give files a quick label (Empty / People & livestock / Survey team) instead of species:
    sets the group and removes their own species labels."""
    labels_ids = list(media_ids)
    con.executemany("UPDATE media SET manual_group=? WHERE id=?", [(group, i) for i in labels_ids])
    con.executemany("DELETE FROM label WHERE media_id=?", [(i,) for i in labels_ids])
    con.commit()


def file_labels(con, deployment_ids, animal_thr, uncertain_thr) -> dict:
    """{media_id: {'group': g, 'labels': [(common, scientific, group, count, note)]}}

    The labels that really apply to each file:
    - a file's own labels win;
    - otherwise the event's labels apply, but NOT to files in the burst that are
      empty, or that were given a quick label (empty / people & livestock / survey team).
    """
    from .grouping import classify

    if not deployment_ids:
        return {}
    q = ",".join("?" * len(deployment_ids))
    ev, md = {}, {}
    for r in con.execute(
        f"""SELECT l.event_id, l.media_id, l.count, l.note, s.common_name, s.scientific_name,
                   IFNULL(s.taxon_group,'') grp
            FROM label l JOIN species s ON s.id=l.species_id JOIN event e ON e.id=l.event_id
            WHERE e.deployment_id IN ({q}) ORDER BY s.common_name""",
        list(deployment_ids),
    ):
        item = (r["common_name"], r["scientific_name"] or "", r["grp"], r["count"], r["note"] or "")
        (md.setdefault(r["media_id"], []) if r["media_id"] else ev.setdefault(r["event_id"], [])).append(item)
    out = {}
    for m in con.execute(f"SELECT * FROM media WHERE deployment_id IN ({q})", list(deployment_ids)):
        g = classify(m["max_animal"], m["max_person"], m["max_vehicle"], animal_thr, uncertain_thr, m["manual_group"])
        own = md.get(m["id"])
        if own:
            labels = own
        elif g in ("animal", "uncertain") or (g == "human" and not m["manual_group"]):
            labels = ev.get(m["event_id"], [])
        else:
            labels = []
        out[m["id"]] = {"group": g, "labels": labels}
    return out


def label_text(labels) -> str:
    """'Patas monkey ×3, Olive baboon' for thumbnails."""
    return ", ".join(f"{c} ×{n}" if n and n > 1 else c for c, _s, _g, n, _note in labels)
