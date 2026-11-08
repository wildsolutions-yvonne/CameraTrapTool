"""Minimal ESRI shapefile writer for points (WGS84), no external libraries.

Writes .shp, .shx, .dbf, .prj and .cpg. Opens in QGIS, ArcGIS, Google Earth Pro, etc.
"""

from __future__ import annotations

import datetime as dt
import struct
from pathlib import Path

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def _field_name(name: str, used: set) -> str:
    base = "".join(c for c in name.upper() if c.isalnum() or c == "_")[:10] or "FIELD"
    n, i = base, 1
    while n in used:
        suffix = str(i)
        n = base[: 10 - len(suffix)] + suffix
        i += 1
    used.add(n)
    return n


def write_points(path, fields: list[tuple[str, str]], rows: list[dict], lon_key="longitude", lat_key="latitude") -> int:
    """fields: [(key, type)] with type 'C' (text), 'N' (whole number), 'F' (decimal), 'D' (date).
    Rows without coordinates are skipped. Returns number of points written."""
    path = Path(path).with_suffix("")
    rows = [r for r in rows if r.get(lon_key) is not None and r.get(lat_key) is not None]
    n = len(rows)

    # ---- .shp / .shx
    rec_len_words = (4 + 16) // 2  # shape type + x + y = 20 bytes = 10 words
    file_len_words = 50 + n * (4 + rec_len_words)
    xs = [float(r[lon_key]) for r in rows] or [0.0]
    ys = [float(r[lat_key]) for r in rows] or [0.0]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    def header(length_words):
        return (
            struct.pack(">7i", 9994, 0, 0, 0, 0, 0, length_words)
            + struct.pack("<2i", 1000, 1)  # version, shape type Point
            + struct.pack("<4d", *bbox)
            + struct.pack("<4d", 0, 0, 0, 0)
        )

    with open(f"{path}.shp", "wb") as shp, open(f"{path}.shx", "wb") as shx:
        shp.write(header(file_len_words))
        shx.write(header(50 + n * 4))
        offset = 50
        for i, r in enumerate(rows, 1):
            shp.write(struct.pack(">2i", i, rec_len_words))
            shp.write(struct.pack("<i2d", 1, float(r[lon_key]), float(r[lat_key])))
            shx.write(struct.pack(">2i", offset, rec_len_words))
            offset += 4 + rec_len_words

    # ---- .dbf (dBASE III)
    used: set = set()
    specs = []
    for key, typ in fields:
        name = _field_name(key, used)
        if typ == "C":
            width = min(254, max([1] + [len(str(r.get(key) or "").encode("utf-8")) for r in rows]))
            specs.append((key, name, "C", width, 0))
        elif typ == "N":
            specs.append((key, name, "N", 12, 0))
        elif typ == "F":
            specs.append((key, name, "N", 19, 6))
        elif typ == "D":
            specs.append((key, name, "D", 8, 0))
    record_len = 1 + sum(s[3] for s in specs)
    header_len = 32 + 32 * len(specs) + 1
    today = dt.date.today()
    with open(f"{path}.dbf", "wb") as dbf:
        dbf.write(struct.pack("<4BIHH20x", 3, today.year - 1900, today.month, today.day, n, header_len, record_len))
        for _key, name, typ, width, dec in specs:
            dbf.write(struct.pack("<11sc4xBB14x", name.encode("ascii"), typ.encode("ascii"), width, dec))
        dbf.write(b"\r")
        for r in rows:
            dbf.write(b" ")
            for key, _name, typ, width, dec in specs:
                v = r.get(key)
                if typ == "C":
                    b = str("" if v is None else v).encode("utf-8")[:width]
                    dbf.write(b.ljust(width, b" "))
                elif typ == "N":
                    s = "" if v is None else (f"{float(v):.{dec}f}" if dec else str(int(round(float(v)))))
                    dbf.write(s.rjust(width)[:width].encode("ascii"))
                elif typ == "D":
                    if isinstance(v, (dt.date, dt.datetime)):
                        dbf.write(v.strftime("%Y%m%d").encode("ascii"))
                    else:
                        dbf.write(b" " * 8)
        dbf.write(b"\x1a")

    Path(f"{path}.prj").write_text(WGS84_PRJ, encoding="ascii")
    Path(f"{path}.cpg").write_text("UTF-8", encoding="ascii")
    return n


def read_points(path):
    """Read back points + attributes (used by the tests, and for checking exports)."""
    path = Path(path).with_suffix("")
    data = Path(f"{path}.shp").read_bytes()
    pts = []
    pos = 100
    while pos < len(data):
        _num, length = struct.unpack(">2i", data[pos : pos + 8])
        _t, x, y = struct.unpack("<i2d", data[pos + 8 : pos + 28])
        pts.append((x, y))
        pos += 8 + length * 2
    d = Path(f"{path}.dbf").read_bytes()
    n, hlen, rlen = struct.unpack("<IHH", d[4:12])
    fields = []
    p = 32
    while d[p] != 0x0D:
        name = d[p : p + 11].split(b"\0")[0].decode()
        typ = chr(d[p + 11])
        width = d[p + 16]
        fields.append((name, typ, width))
        p += 32
    rows = []
    for i in range(n):
        rec = d[hlen + i * rlen + 1 : hlen + (i + 1) * rlen]
        row, o = {}, 0
        for name, typ, width in fields:
            row[name] = rec[o : o + width].decode("utf-8", "replace").strip()
            o += width
        rows.append(row)
    return pts, rows
