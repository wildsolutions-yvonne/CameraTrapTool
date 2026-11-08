"""Web Mercator tile maths (the system used by OpenStreetMap and satellite tile services)."""

from __future__ import annotations

import math

TILE = 256


def lonlat_to_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = TILE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def pixel_to_lonlat(x: float, y: float, zoom: int) -> tuple[float, float]:
    n = TILE * (2 ** zoom)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def fit_zoom(points, width, height, max_zoom=16, min_zoom=2, pad=60):
    """Largest zoom at which all (lon, lat) points fit in width x height pixels."""
    if not points:
        return 6
    if len(points) == 1:
        return 14
    for z in range(max_zoom, min_zoom - 1, -1):
        xs, ys = zip(*(lonlat_to_pixel(lo, la, z) for lo, la in points))
        if max(xs) - min(xs) <= width - 2 * pad and max(ys) - min(ys) <= height - 2 * pad:
            return z
    return min_zoom


def format_latlon(lat: float, lon: float) -> str:
    return f"{abs(lat):.5f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.5f}°{'E' if lon >= 0 else 'W'}"
