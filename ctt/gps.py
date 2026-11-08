"""Reading waypoints from GPS files (GPX, CSV, Excel)."""

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Waypoint:
    name: str
    lat: float
    lon: float
    elevation: float | None = None
    time: str = ""


def read_waypoints(path) -> list[Waypoint]:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".gpx":
        return read_gpx(path)
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
        return _from_table(rows)
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        first = f.readline()
        f.seek(0)
        delim = max([",", ";", "\t"], key=first.count)
        return _from_table(list(csv.reader(f, delimiter=delim)))


def read_gpx(path) -> list[Waypoint]:
    root = ET.parse(path).getroot()
    out = []

    def tag(e):
        return e.tag.split("}")[-1]

    def child(e, name):
        for c in e:
            if tag(c) == name:
                return c.text
        return None

    for e in root.iter():
        if tag(e) in ("wpt", "rtept"):
            try:
                lat, lon = float(e.get("lat")), float(e.get("lon"))
            except (TypeError, ValueError):
                continue
            ele = child(e, "ele")
            out.append(Waypoint(
                (child(e, "name") or f"WP{len(out) + 1:03d}").strip(), lat, lon,
                float(ele) if ele not in (None, "") else None, child(e, "time") or "",
            ))
    return out


_LAT = re.compile(r"^(lat|latitude|y|lat_dd|latitude_dd)$", re.I)
_LON = re.compile(r"^(lon|long|lng|longitude|x|lon_dd|longitude_dd)$", re.I)
_NAME = re.compile(r"^(name|ident|id|waypoint|wpt|station|site|label)$", re.I)
_ELE = re.compile(r"^(ele|elev|elevation|alt|altitude|height)(\s*\(m\))?$", re.I)


def _from_table(rows) -> list[Waypoint]:
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return []
    head = [str(h).strip() for h in rows[0]]

    def find(rx):
        for i, h in enumerate(head):
            if rx.match(h):
                return i
        return None

    ilat, ilon, iname, iele = find(_LAT), find(_LON), find(_NAME), find(_ELE)
    if ilat is None or ilon is None:
        raise ValueError(
            "Could not find latitude/longitude columns. Name them 'lat' and 'lon' "
            "(or 'latitude'/'longitude'), in decimal degrees."
        )
    out = []
    for i, r in enumerate(rows[1:], 1):
        try:
            lat = float(str(r[ilat]).replace(",", "."))
            lon = float(str(r[ilon]).replace(",", "."))
        except (ValueError, IndexError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        ele = None
        if iele is not None and iele < len(r):
            try:
                ele = float(str(r[iele]).replace(",", "."))
            except ValueError:
                pass
        name = str(r[iname]).strip() if iname is not None and iname < len(r) else f"Row {i}"
        out.append(Waypoint(name or f"Row {i}", lat, lon, ele))
    return out
