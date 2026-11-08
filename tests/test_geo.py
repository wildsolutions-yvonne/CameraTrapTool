import pytest

from ctt import geo


def test_roundtrip():
    for lon, lat in [(37.0399, 0.1231), (-70.5, -33.4), (0, 0)]:
        x, y = geo.lonlat_to_pixel(lon, lat, 15)
        lo, la = geo.pixel_to_lonlat(x, y, 15)
        assert lo == pytest.approx(lon, abs=1e-9) and la == pytest.approx(lat, abs=1e-9)


def test_known_tile():
    # Nairobi (36.82E, 1.29S) is in OSM tile z=10 x=616 y=515
    x, y = geo.lonlat_to_pixel(36.82, -1.29, 10)
    assert (int(x // 256), int(y // 256)) == (616, 515)


def test_fit_zoom():
    assert geo.fit_zoom([(37.0, 0.1)], 800, 600) == 14
    z = geo.fit_zoom([(37.0, 0.1), (37.1, 0.2)], 800, 600)
    assert 10 <= z <= 13
    assert geo.format_latlon(-1.29, 36.82) == "1.29000°S, 36.82000°E"
