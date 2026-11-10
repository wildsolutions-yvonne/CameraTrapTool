"""SQLite storage for projects, stations, deployments, media, events, labels and species.

All data lives in one database file (default: %APPDATA%/CameraTrapTool/cameratraptool.db).
Original image/video files are never moved or modified.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS species (
    id INTEGER PRIMARY KEY,
    common_name TEXT NOT NULL UNIQUE,
    scientific_name TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT '',
    animal_threshold REAL NOT NULL DEFAULT 0.20,
    uncertain_threshold REAL NOT NULL DEFAULT 0.05,
    event_gap_seconds INTEGER NOT NULL DEFAULT 60,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS station (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    notes TEXT DEFAULT '',
    UNIQUE(project_id, name)
);

CREATE TABLE IF NOT EXISTS deployment (
    id INTEGER PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES station(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    folder TEXT NOT NULL,
    start_date TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    camera TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    time_offset_seconds INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT
);

-- One row per image or video. max_* are the highest detector confidences found.
-- The Animal/Uncertain/Human-Vehicle/Empty group is computed from these and the
-- project thresholds, so changing thresholds never needs a re-run.
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    deployment_id INTEGER NOT NULL REFERENCES deployment(id) ON DELETE CASCADE,
    relpath TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('image', 'video')),
    taken_at TEXT,                 -- original camera timestamp (ISO), before offset
    max_animal REAL,
    max_person REAL,
    max_vehicle REAL,
    best_frame_seconds REAL,       -- video: time of the frame with the highest animal score
    manual_group TEXT,             -- user override: 'animal','human','empty' or NULL
    event_id INTEGER REFERENCES event(id) ON DELETE SET NULL,
    error TEXT,
    UNIQUE(deployment_id, relpath)
);

CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY,
    deployment_id INTEGER NOT NULL REFERENCES deployment(id) ON DELETE CASCADE,
    start_at TEXT,
    end_at TEXT,
    note TEXT DEFAULT ''
);

-- media_id NULL  -> label applies to the whole event
-- media_id set   -> label applies only to that file (overrides the event labels for it)
CREATE TABLE IF NOT EXISTS label (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    media_id INTEGER REFERENCES media(id) ON DELETE CASCADE,
    species_id INTEGER NOT NULL REFERENCES species(id),
    count INTEGER NOT NULL DEFAULT 1,
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS media_note (
    media_id INTEGER PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
    note TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_media_dep ON media(deployment_id);
CREATE INDEX IF NOT EXISTS ix_media_event ON media(event_id);
CREATE INDEX IF NOT EXISTS ix_label_event ON label(event_id);
"""


def default_db_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    folder = Path(base) / "CameraTrapTool"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "cameratraptool.db"


# Columns added after version 0.1. Existing databases are upgraded in place.
MIGRATIONS = {
    "species": [
        ("taxon_group", "TEXT DEFAULT ''"),
        ("last_used_at", "TEXT"),
    ],
    "station": [("elevation", "REAL")],
    # 1 = start/end of the deployment come from the first/last file (default)
    "deployment": [("dates_auto", "INTEGER NOT NULL DEFAULT 1")],
    "project": [
        ("photo_path", "TEXT DEFAULT ''"),
        ("location", "TEXT DEFAULT ''"),
    ],
}

# Suggested taxon groups. 'Domestic' and 'Human' count as people & livestock.
TAXON_GROUPS = [
    "Primates", "Carnivores", "Ungulates", "Rodents", "Lagomorphs", "Hyraxes",
    "Elephants", "Other mammals", "Birds", "Reptiles", "Domestic", "Human", "Other",
]
DOMESTIC_GROUPS = {"Domestic", "Human"}


def _migrate(con):
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    con.commit()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or default_db_path()))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


# ---------------------------------------------------------------- projects
def add_project(con, name, notes="", photo_path="", location=""):
    cur = con.execute(
        "INSERT INTO project(name, notes, photo_path, location) VALUES (?,?,?,?)", (name, notes, photo_path, location)
    )
    con.commit()
    return cur.lastrowid


def list_projects(con):
    return con.execute("SELECT * FROM project ORDER BY name").fetchall()


def get_project(con, project_id):
    return con.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()


def update_project(con, project_id, **fields):
    _update(con, "project", project_id, fields)


def delete_project(con, project_id):
    con.execute("DELETE FROM project WHERE id=?", (project_id,))
    con.commit()


# ---------------------------------------------------------------- stations
def add_station(con, project_id, name, latitude=None, longitude=None, notes="", elevation=None):
    cur = con.execute(
        "INSERT INTO station(project_id, name, latitude, longitude, notes, elevation) VALUES (?,?,?,?,?,?)",
        (project_id, name, latitude, longitude, notes, elevation),
    )
    con.commit()
    return cur.lastrowid


def list_stations(con, project_id):
    return con.execute(
        "SELECT * FROM station WHERE project_id=? ORDER BY name", (project_id,)
    ).fetchall()


def update_station(con, station_id, **fields):
    _update(con, "station", station_id, fields)


def delete_station(con, station_id):
    con.execute("DELETE FROM station WHERE id=?", (station_id,))
    con.commit()


# ---------------------------------------------------------------- deployments
def add_deployment(con, station_id, name, folder, start_date="", end_date="", camera="", notes="", dates_auto=None):
    if dates_auto is None:
        dates_auto = 0 if (start_date or end_date) else 1
    cur = con.execute(
        "INSERT INTO deployment(station_id, name, folder, start_date, end_date, camera, notes, dates_auto)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (station_id, name, str(folder), start_date, end_date, camera, notes, int(dates_auto)),
    )
    con.commit()
    return cur.lastrowid


def list_deployments(con, station_id):
    return con.execute(
        "SELECT * FROM deployment WHERE station_id=? ORDER BY start_date, name", (station_id,)
    ).fetchall()


def get_deployment(con, deployment_id):
    return con.execute(
        "SELECT d.*, s.project_id, s.name AS station_name FROM deployment d"
        " JOIN station s ON s.id=d.station_id WHERE d.id=?",
        (deployment_id,),
    ).fetchone()


def update_deployment(con, deployment_id, **fields):
    _update(con, "deployment", deployment_id, fields)


def file_period(con, deployment_id):
    """(first, last) file time of a deployment, with the time correction applied."""
    import datetime as _dt

    d = con.execute("SELECT time_offset_seconds FROM deployment WHERE id=?", (deployment_id,)).fetchone()
    r = con.execute(
        "SELECT MIN(taken_at) a, MAX(taken_at) b FROM media WHERE deployment_id=? AND taken_at IS NOT NULL",
        (deployment_id,),
    ).fetchone()
    off = _dt.timedelta(seconds=(d["time_offset_seconds"] or 0) if d else 0)

    def p(v):
        try:
            return _dt.datetime.fromisoformat(v) + off if v else None
        except ValueError:
            return None

    return p(r["a"]), p(r["b"])


def deployment_period(con, dep):
    """(start, end, source) of a deployment. source = 'files' or 'dates'."""
    import datetime as _dt

    first, last = file_period(con, dep["id"])
    if dep["dates_auto"] or not (dep["start_date"] and dep["end_date"]):
        return first, last, "files"

    def d(v, end=False):
        try:
            t = _dt.datetime.fromisoformat(v.strip())
        except ValueError:
            return None
        if len(v.strip()) <= 10 and end:   # date only: count the whole last day
            t += _dt.timedelta(days=1)
        return t

    return d(dep["start_date"]), d(dep["end_date"], end=True), "dates"


def delete_deployment(con, deployment_id):
    con.execute("DELETE FROM deployment WHERE id=?", (deployment_id,))
    con.commit()


# ---------------------------------------------------------------- species
def add_species(con, common_name, scientific_name="", taxon_group=""):
    common_name = common_name.strip()
    if not common_name:
        raise ValueError("A species needs a common name.")
    row = con.execute("SELECT id FROM species WHERE common_name=? COLLATE NOCASE", (common_name,)).fetchone()
    if row:
        if scientific_name:
            con.execute("UPDATE species SET scientific_name=? WHERE id=?", (scientific_name.strip(), row["id"]))
        if taxon_group:
            con.execute("UPDATE species SET taxon_group=? WHERE id=?", (taxon_group.strip(), row["id"]))
        con.commit()
        return row["id"]
    cur = con.execute(
        "INSERT INTO species(common_name, scientific_name, taxon_group) VALUES (?,?,?)",
        (common_name, scientific_name.strip(), (taxon_group or "").strip()),
    )
    con.commit()
    return cur.lastrowid


def update_species(con, species_id, **fields):
    if "common_name" in fields:
        name = fields["common_name"].strip()
        if not name:
            raise ValueError("A species needs a common name.")
        clash = con.execute(
            "SELECT id FROM species WHERE common_name=? COLLATE NOCASE AND id<>?", (name, species_id)
        ).fetchone()
        if clash:
            raise ValueError(f"'{name}' is already in the species list.")
        fields["common_name"] = name
    _update(con, "species", species_id, fields)


def list_species(con, recent_first=False):
    order = "CASE WHEN last_used_at IS NULL THEN 1 ELSE 0 END, last_used_at DESC, common_name" if recent_first else "common_name"
    return con.execute(f"SELECT * FROM species ORDER BY {order}").fetchall()


def touch_species(con, species_ids):
    """Remember when species were last used, so they appear at the top of the picker."""
    import datetime as _dt

    now = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
    con.executemany("UPDATE species SET last_used_at=? WHERE id=?", [(now, i) for i in species_ids])
    con.commit()


def species_usage(con, species_id) -> int:
    return con.execute("SELECT COUNT(*) FROM label WHERE species_id=?", (species_id,)).fetchone()[0]


def delete_species(con, species_id):
    used = con.execute("SELECT COUNT(*) FROM label WHERE species_id=?", (species_id,)).fetchone()[0]
    if used:
        raise ValueError(f"This species is used in {used} label(s) and cannot be deleted.")
    con.execute("DELETE FROM species WHERE id=?", (species_id,))
    con.commit()


def import_species_table(con, path) -> int:
    """Import a species list from CSV or Excel.

    Column 1 = common name, optional column 2 = scientific name, optional column 3 = taxon group. A header row is
    detected and skipped if its first cell is 'common', 'name' or 'species'.
    """
    path = Path(path)
    rows: list[list[str]] = []
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True).active
        for r in ws.iter_rows(values_only=True):
            rows.append(["" if v is None else str(v) for v in r])
    else:
        import csv

        with open(path, newline="", encoding="utf-8-sig") as f:
            first = f.readline()
            f.seek(0)
            # Excel in many locales saves CSV with ';'. Pick the most frequent separator.
            delim = max([",", ";", "\t"], key=first.count) if any(c in first for c in ",;\t") else ","
            rows = [r for r in csv.reader(f, delimiter=delim)]
    n = 0
    for i, r in enumerate(rows):
        if not r or not r[0].strip():
            continue
        if i == 0 and r[0].strip().lower() in ("common", "common name", "common_name", "name", "species"):
            continue
        add_species(con, r[0], r[1] if len(r) > 1 else "", r[2] if len(r) > 2 else "")
        n += 1
    return n


# ---------------------------------------------------------------- helpers
def _update(con, table, row_id, fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), row_id))
    con.commit()
