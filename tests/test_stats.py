import datetime as dt

import pytest

from ctt import db, labels, processing, stats


def _media(con, dep, rel, when, animal=0.9, person=0.0):
    con.execute(
        "INSERT INTO media(deployment_id, relpath, kind, taken_at, max_animal, max_person, max_vehicle)"
        " VALUES (?,?,?,?,?,?,0)",
        (dep, rel, "image", when.isoformat(sep=" "), animal, person),
    )


@pytest.fixture
def proj(tmp_path):
    con = db.connect(tmp_path / "s.db")
    pid = db.add_project(con, "P")
    a = db.add_station(con, pid, "A", 0.1, 37.0, elevation=1800)
    b = db.add_station(con, pid, "B", 0.2, 37.1)
    c = db.add_station(con, pid, "C", 0.3, 37.2)  # no deployment: no effort
    # A: 10 nights, camera ran the whole time
    da = db.add_deployment(con, a, "A1", tmp_path, "2026-03-01", "2026-03-10")
    # B: 20 nights planned, but last file on day 5 -> stopped early
    dbb = db.add_deployment(con, b, "B1", tmp_path, "2026-03-01", "2026-03-20")
    t = dt.datetime(2026, 3, 1, 6, 0)
    _media(con, da, "a1.jpg", t)                                    # zebra
    _media(con, da, "a2.jpg", t + dt.timedelta(seconds=5))          # same event
    _media(con, da, "a3.jpg", t + dt.timedelta(days=2, hours=16))   # leopard 22:00
    _media(con, da, "a4.jpg", t + dt.timedelta(days=9, hours=12), animal=0.0)  # empty, last file day 10
    _media(con, dbb, "b1.jpg", t + dt.timedelta(hours=1))           # zebra
    _media(con, dbb, "b2.jpg", t + dt.timedelta(days=4), animal=0.0, person=0.9)  # herder + goats
    _media(con, dbb, "b3.jpg", t + dt.timedelta(days=4, hours=2), animal=0.0)     # empty
    con.commit()
    processing.build_events(con, da, 60)
    processing.build_events(con, dbb, 60)
    zebra = db.add_species(con, "Plains zebra", "Equus quagga", "Ungulates")
    leopard = db.add_species(con, "Leopard", "Panthera pardus", "Carnivores")
    goat = db.add_species(con, "Goat", "Capra hircus", "Domestic")
    ev = lambda dep: labels.events_to_label(con, dep, 0.2, 0.05)
    ea, eb = ev(da), ev(dbb)
    labels.set_event_labels(con, ea[0]["id"], [(zebra, 3, "")])
    labels.set_event_labels(con, ea[1]["id"], [(leopard, 1, "")])
    labels.set_event_labels(con, eb[0]["id"], [(zebra, 5, "")])
    labels.set_event_labels(con, eb[1]["id"], [(goat, 12, "")])
    return con, pid, dict(a=a, b=b, c=c, zebra=zebra, leopard=leopard, goat=goat)


def test_effort_and_uptime(proj):
    con, pid, ids = proj
    s = stats.project_stats(con, pid)
    eff = s.station_effort()
    assert eff[ids["a"]]["trap_nights"] == pytest.approx(10)       # 1-10 March inclusive
    assert eff[ids["a"]]["stopped_early"] == 0
    assert eff[ids["b"]]["stopped_early"] == 1                     # last file 5 March, end 20 March
    assert eff[ids["b"]]["trap_nights"] == pytest.approx(4 + 8 / 24)  # 1 Mar 00:00 -> last file 5 Mar 08:00
    assert eff[ids["b"]]["trap_hours"] == pytest.approx(104)


def test_summaries(proj):
    con, pid, ids = proj
    s = stats.project_stats(con, pid)
    sp = {r["species"]: r for r in s.species_summary()}
    assert sp["Plains zebra"]["records"] == 2 and sp["Plains zebra"]["individuals"] == 8
    assert sp["Plains zebra"]["naive_occupancy"] == pytest.approx(1.0)   # A and B (C has no effort)
    assert sp["Leopard"]["naive_occupancy"] == pytest.approx(0.5)
    st = {r["station"]: r for r in s.station_summary()}
    assert st["A"]["richness"] == 2 and st["B"]["richness"] == 1          # goat not counted
    assert st["A"]["wild_rai"] == pytest.approx(20.0)                     # 2 records / 10 TN * 100
    assert st["A"]["false_trigger_rate"] == pytest.approx(0.25)
    assert st["A"]["elevation"] == 1800
    best, worst = s.best_worst()
    assert best["station"] == "B" and worst["station"] == "A"   # B: 1 record in 4.33 nights = 23.1 > A: 20.0
    assert s.matrix(("group", "Domestic"))[ids["goat"]][ids["b"]] == 1
    assert set(s.matrix(("species", ids["zebra"]))) == {ids["zebra"]}
    assert s.monthly() == {"2026-03": 4}
    acc = s.accumulation()
    assert acc[-1][1] == 2 and acc[0][0] == dt.date(2026, 3, 1)
    assert sorted(round(h) for h in s.activity_hours(("species", ids["leopard"]))) == [22]


def test_overlap():
    same = stats.activity_overlap([6, 7, 8, 9], [6, 7, 8, 9])
    apart = stats.activity_overlap([1, 2, 3, 2.5], [13, 14, 15, 14.5])
    assert same == pytest.approx(1.0, abs=0.01)
    assert apart < 0.05
    assert stats.activity_overlap([1], [2, 3]) is None


def test_excel_and_shapefiles(proj, tmp_path):
    from openpyxl import load_workbook

    from ctt import export, shapefile

    con, pid, ids = proj
    x = tmp_path / "out.xlsx"
    export.export_project(con, pid, x)
    wb = load_workbook(x)
    assert wb.sheetnames == ["Observations", "Stations", "Species", "Records per station",
                             "RAI per station", "Deployments", "Definitions"]
    st = {r[0].value: r for r in wb["Stations"].iter_rows(min_row=2)}
    assert st["A"][5].value == 10.0 and st["A"][14].value == 20.0

    res = export.export_shapefiles(con, pid, tmp_path / "shp", ("species", ids["zebra"]), "Plains zebra")
    assert res["stations"] == 3 and res["events"] == 2
    pts, rows = shapefile.read_points(tmp_path / "shp" / "Plains_zebra_stations")
    assert pts[0] == (37.0, 0.1)
    assert rows[0]["STATION"] == "A" and rows[0]["RECORDS"] == "1" and float(rows[0]["RAI"]) == 10.0
    assert rows[2]["PRESENT"] == "0"
    pts, rows = shapefile.read_points(tmp_path / "shp" / "Plains_zebra_events")
    assert [r["COUNT"] for r in rows] == ["3", "5"] and rows[0]["DATE"] == "20260301"

    # independent check with pyshp when available (installed in the build)
    pyshp = pytest.importorskip("shapefile")
    r = pyshp.Reader(str(tmp_path / "shp" / "Plains_zebra_stations"))
    assert r.shapeType == pyshp.POINT and len(r) == 3
    assert r.record(0)["STATION"] == "A" and tuple(r.shape(0).points[0]) == (37.0, 0.1)
