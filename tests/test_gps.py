import pytest

from ctt import gps

GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="GPSMAP 66" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="0.123150" lon="37.039876"><ele>1765.3</ele><time>2026-03-01T06:12:00Z</time><name>TUM18</name></wpt>
  <wpt lat="-0.5" lon="36.9"><name>Camp</name></wpt>
  <trk><trkseg><trkpt lat="1" lon="2"/></trkseg></trk>
</gpx>"""


def test_gpx(tmp_path):
    p = tmp_path / "w.gpx"
    p.write_text(GPX, encoding="utf-8")
    w = gps.read_waypoints(p)
    assert [x.name for x in w] == ["TUM18", "Camp"]
    assert w[0].lat == pytest.approx(0.12315) and w[0].elevation == pytest.approx(1765.3)
    assert w[1].elevation is None


def test_csv_semicolon_decimal_comma(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text("Name;Latitude;Longitude;Elevation\nCT01;0,1231;37,0399;1765\nbad;x;y;\n", encoding="utf-8")
    w = gps.read_waypoints(p)
    assert len(w) == 1 and w[0].name == "CT01" and w[0].lon == pytest.approx(37.0399) and w[0].elevation == 1765


def test_excel(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["site", "lat", "lon"])
    wb.active.append(["A", 0.5, 37.5])
    p = tmp_path / "w.xlsx"
    wb.save(p)
    assert gps.read_waypoints(p)[0].name == "A"


def test_missing_columns(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        gps.read_waypoints(p)
