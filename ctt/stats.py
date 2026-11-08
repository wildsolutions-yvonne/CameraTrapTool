"""Ecological statistics for a project.

Definitions (also shown in the app):
- Record: one labelled *event* (photos/videos closer in time than the project's
  event gap) at one station, per species.
- Trap period of a deployment: from its start date (00:00) to its end date (24:00).
  Uptime check: if the last file is more than 24 h before the end date, the camera
  probably stopped early (full card, flat battery, damage) and the period ends at
  the last file instead. Without dates, first-to-last file is used.
- Trap-nights = trap hours / 24.
- RAI (relative abundance index) = records / trap-nights x 100.
- Naive occupancy = stations with >= 1 record / stations with trap effort.
- Species richness counts wild species only (taxon groups 'Domestic' and 'Human' excluded).
- False-trigger rate = files without animal, person or vehicle / processed files.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field

from .db import DOMESTIC_GROUPS
from .grouping import classify
from .processing import corrected_time, parse_ts


@dataclass
class DeploymentEffort:
    deployment_id: int
    station_id: int
    name: str
    start: dt.datetime | None
    stop: dt.datetime | None
    nominal_stop: dt.datetime | None
    first_file: dt.datetime | None
    last_file: dt.datetime | None
    stopped_early: bool
    trap_hours: float

    @property
    def trap_nights(self) -> float:
        return self.trap_hours / 24.0


@dataclass
class Record:
    event_id: int
    station_id: int
    deployment_id: int
    species_id: int
    when: dt.datetime | None
    count: int


@dataclass
class ProjectStats:
    project: dict
    stations: list[dict]
    species: dict                 # id -> row (dict)
    effort: list[DeploymentEffort]
    records: list[Record]
    files: dict = field(default_factory=dict)   # station_id -> {group: n}

    # ---------------------------------------------------------- effort
    def station_effort(self) -> dict:
        out = defaultdict(lambda: {"trap_hours": 0.0, "trap_nights": 0.0, "deployments": 0, "stopped_early": 0})
        for e in self.effort:
            s = out[e.station_id]
            s["trap_hours"] += e.trap_hours
            s["trap_nights"] += e.trap_nights
            s["deployments"] += 1
            s["stopped_early"] += int(e.stopped_early)
        return out

    def total_trap_nights(self) -> float:
        return sum(e.trap_nights for e in self.effort)

    def total_trap_hours(self) -> float:
        return sum(e.trap_hours for e in self.effort)

    # ---------------------------------------------------------- filtering
    def species_in(self, taxon=None) -> set:
        """taxon: None (all), ('species', id) or ('group', name)."""
        if taxon is None:
            return set(self.species)
        kind, val = taxon
        if kind == "species":
            return {val}
        return {sid for sid, s in self.species.items() if (s.get("taxon_group") or "") == val}

    def wild_species(self) -> set:
        return {sid for sid, s in self.species.items() if (s.get("taxon_group") or "") not in DOMESTIC_GROUPS}

    def recs(self, taxon=None):
        keep = self.species_in(taxon)
        return [r for r in self.records if r.species_id in keep]

    # ---------------------------------------------------------- tables
    def matrix(self, taxon=None) -> dict:
        """{species_id: {station_id: n_records}}"""
        m = defaultdict(lambda: defaultdict(int))
        for r in self.recs(taxon):
            m[r.species_id][r.station_id] += 1
        return m

    def rai(self, taxon=None) -> dict:
        """{species_id: {station_id: RAI}} plus 'all' station totals under key None."""
        eff = self.station_effort()
        out = {}
        for sid, row in self.matrix(taxon).items():
            out[sid] = {st: (n / eff[st]["trap_nights"] * 100 if eff[st]["trap_nights"] else None) for st, n in row.items()}
        return out

    def species_summary(self, taxon=None) -> list[dict]:
        eff = self.station_effort()
        stations_with_effort = [s["id"] for s in self.stations if eff[s["id"]]["trap_nights"] > 0]
        tn = self.total_trap_nights()
        rows = []
        for sid, per_station in self.matrix(taxon).items():
            n = sum(per_station.values())
            ind = sum(r.count for r in self.records if r.species_id == sid)
            occ = len([s for s in per_station if s in stations_with_effort])
            whens = [r.when for r in self.records if r.species_id == sid and r.when]
            sp = self.species[sid]
            rows.append({
                "species_id": sid,
                "species": sp["common_name"],
                "scientific_name": sp.get("scientific_name") or "",
                "group": sp.get("taxon_group") or "",
                "records": n,
                "individuals": ind,
                "stations": occ,
                "naive_occupancy": occ / len(stations_with_effort) if stations_with_effort else None,
                "rai": n / tn * 100 if tn else None,
                "first": min(whens) if whens else None,
                "last": max(whens) if whens else None,
            })
        rows.sort(key=lambda r: -r["records"])
        return rows

    def station_summary(self) -> list[dict]:
        eff = self.station_effort()
        wild = self.wild_species()
        rows = []
        for s in self.stations:
            st = s["id"]
            recs = [r for r in self.records if r.station_id == st]
            wild_recs = [r for r in recs if r.species_id in wild]
            f = self.files.get(st, {})
            processed = sum(v for k, v in f.items() if k != "pending")
            empty = f.get("empty", 0)
            tnights = eff[st]["trap_nights"]
            rows.append({
                "station_id": st,
                "station": s["name"],
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "elevation": s.get("elevation"),
                "deployments": eff[st]["deployments"],
                "trap_nights": tnights,
                "trap_hours": eff[st]["trap_hours"],
                "stopped_early": eff[st]["stopped_early"],
                "files": processed,
                "empty_files": empty,
                "false_trigger_rate": empty / processed if processed else None,
                "records": len(recs),
                "wild_records": len(wild_recs),
                "richness": len({r.species_id for r in wild_recs}),
                "wild_rai": len(wild_recs) / tnights * 100 if tnights else None,
                "species": sorted({self.species[r.species_id]["common_name"] for r in recs}),
            })
        return rows

    def best_worst(self):
        """Best/worst station by wild-animal RAI (ties broken by richness). None if <1 station with effort."""
        rows = [r for r in self.station_summary() if r["trap_nights"] > 0]
        if not rows:
            return None, None
        key = lambda r: (r["wild_rai"] or 0, r["richness"])
        return max(rows, key=key), min(rows, key=key)

    # ---------------------------------------------------------- time
    def monthly(self, taxon=None) -> dict:
        """{'YYYY-MM': n_records}"""
        out = defaultdict(int)
        for r in self.recs(taxon):
            if r.when:
                out[f"{r.when:%Y-%m}"] += 1
        return dict(sorted(out.items()))

    def activity_hours(self, taxon=None) -> list[float]:
        return [r.when.hour + r.when.minute / 60 for r in self.recs(taxon) if r.when]

    def accumulation(self):
        """Species accumulation over survey days: [(date, cumulative wild species)]"""
        wild = self.wild_species()
        firsts = {}
        for r in sorted((r for r in self.records if r.when and r.species_id in wild), key=lambda r: r.when):
            firsts.setdefault(r.species_id, r.when.date())
        if not firsts:
            return []
        days = sorted(set(firsts.values()))
        out, seen = [], 0
        for d in days:
            seen += sum(1 for v in firsts.values() if v == d)
            out.append((d, seen))
        return out


# ---------------------------------------------------------------- building
def _date(value):
    if not value:
        return None
    try:
        return dt.datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def deployment_effort(con, dep) -> DeploymentEffort:
    off = dep["time_offset_seconds"] or 0
    times = con.execute(
        "SELECT MIN(taken_at) a, MAX(taken_at) b FROM media WHERE deployment_id=? AND taken_at IS NOT NULL",
        (dep["id"],),
    ).fetchone()
    first = corrected_time(times["a"], off)
    last = corrected_time(times["b"], off)
    start = _date(dep["start_date"]) or first
    nominal = _date(dep["end_date"])
    nominal = nominal + dt.timedelta(days=1) if nominal else last
    stop, early = nominal, False
    if last and nominal and last < nominal - dt.timedelta(hours=24) and (start is None or last > start):
        stop, early = last, True
    hours = max(0.0, (stop - start).total_seconds() / 3600) if start and stop else 0.0
    return DeploymentEffort(dep["id"], dep["station_id"], dep["name"], start, stop, nominal, first, last, early, hours)


def project_stats(con, project_id) -> ProjectStats:
    p = dict(con.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone())
    stations = [dict(r) for r in con.execute("SELECT * FROM station WHERE project_id=? ORDER BY name", (project_id,))]
    species = {r["id"]: dict(r) for r in con.execute("SELECT * FROM species")}
    deps = con.execute(
        "SELECT d.* FROM deployment d JOIN station s ON s.id=d.station_id WHERE s.project_id=?", (project_id,)
    ).fetchall()
    effort = [deployment_effort(con, d) for d in deps]
    offsets = {d["id"]: d["time_offset_seconds"] or 0 for d in deps}

    # records: per event and species (event labels + per-file overrides), max count
    rows = con.execute(
        """SELECT e.id ev, e.start_at, e.deployment_id dep, d.station_id st, l.species_id sp, l.count n
           FROM label l JOIN event e ON e.id=l.event_id JOIN deployment d ON d.id=e.deployment_id
           JOIN station s ON s.id=d.station_id WHERE s.project_id=?""",
        (project_id,),
    ).fetchall()
    agg = {}
    for r in rows:
        k = (r["ev"], r["sp"])
        if k not in agg:
            agg[k] = Record(r["ev"], r["st"], r["dep"], r["sp"], corrected_time(r["start_at"], offsets[r["dep"]]), r["n"])
        else:
            agg[k].count = max(agg[k].count, r["n"])
    records = list(agg.values())

    files = defaultdict(lambda: defaultdict(int))
    for m in con.execute(
        """SELECT d.station_id st, m.max_animal, m.max_person, m.max_vehicle, m.manual_group
           FROM media m JOIN deployment d ON d.id=m.deployment_id JOIN station s ON s.id=d.station_id
           WHERE s.project_id=?""",
        (project_id,),
    ):
        g = classify(m["max_animal"], m["max_person"], m["max_vehicle"],
                     p["animal_threshold"], p["uncertain_threshold"], m["manual_group"]) or "pending"
        files[m["st"]][g] += 1
    return ProjectStats(p, stations, species, effort, records, {k: dict(v) for k, v in files.items()})


# ---------------------------------------------------------------- activity
def circular_density(hours, grid=None, kappa=12.0):
    """Smoothed activity density over 24 h (von Mises kernel). Integrates to 1 over 0-24 h."""
    import numpy as np

    grid = np.linspace(0, 24, 289) if grid is None else grid
    if not len(hours):
        return grid, np.zeros_like(grid)
    th = np.asarray(hours) / 24 * 2 * np.pi
    g = grid / 24 * 2 * np.pi
    k = np.exp(kappa * np.cos(g[:, None] - th[None, :])) / (2 * np.pi * np.i0(kappa))
    dens = k.mean(axis=1) * (2 * np.pi / 24)  # per hour
    return grid, dens


def activity_overlap(hours_a, hours_b, kappa=12.0):
    """Overlap coefficient (0-1) between two activity patterns: area under the
    minimum of both smoothed densities (like Dhat1 in R's 'overlap' package, but with
    fixed smoothing). For publication use the exported data with R 'overlap'."""
    import numpy as np

    if len(hours_a) < 2 or len(hours_b) < 2:
        return None
    grid = np.linspace(0, 24, 1441)
    _, a = circular_density(hours_a, grid, kappa)
    _, b = circular_density(hours_b, grid, kappa)
    m = np.minimum(a, b)
    return float(np.sum((m[:-1] + m[1:]) / 2 * np.diff(grid)))


def fmt(v, digits=1):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)
