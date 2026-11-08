import csv
import datetime as dt

import numpy as np
import pytest
from PIL import Image

from ctt import db, processing, labels, export, grouping
from ctt.detector import postprocess, preprocess, Detection


class FakeDetector:
    """Returns a fixed score per file based on the image's mean colour."""

    def detect(self, bgr):
        v = float(bgr.mean()) / 255.0
        if v > 0.7:
            return [Detection("animal", 0.9, (0.1, 0.1, 0.5, 0.5))]
        if v > 0.45:
            return [Detection("animal", 0.1, (0.1, 0.1, 0.2, 0.2))]
        if v > 0.3:
            return [Detection("person", 0.8, (0.1, 0.1, 0.5, 0.9))]
        return []


def _img(path, value, when):
    im = Image.new("RGB", (64, 48), (value, value, value))
    exif = Image.Exif()
    exif[0x0132] = when.strftime("%Y:%m:%d %H:%M:%S")
    im.save(path, exif=exif)


@pytest.fixture
def setup(tmp_path):
    folder = tmp_path / "DCIM"
    folder.mkdir()
    t0 = dt.datetime(2026, 3, 1, 6, 0, 0)
    # burst 1: animal (3 photos within 2 s)
    for i in range(3):
        _img(folder / f"a{i}.jpg", 230, t0 + dt.timedelta(seconds=i))
    # 10 min later: empty
    _img(folder / "e0.jpg", 10, t0 + dt.timedelta(minutes=10))
    # uncertain
    _img(folder / "u0.jpg", 140, t0 + dt.timedelta(minutes=20))
    # person
    _img(folder / "p0.jpg", 95, t0 + dt.timedelta(minutes=30))
    con = db.connect(tmp_path / "t.db")
    pid = db.add_project(con, "Laikipia 2026")
    sid = db.add_station(con, pid, "CT01", 0.3, 36.9)
    did = db.add_deployment(con, sid, "CT01-Mar", folder)
    return con, pid, did, folder


def test_pipeline(setup, tmp_path):
    con, pid, did, folder = setup
    assert processing.scan_deployment(con, did) == 6
    assert processing.scan_deployment(con, did) == 0  # idempotent
    res = processing.run_detection(con, did, FakeDetector())
    assert res == {"processed": 6, "errors": 0, "remaining": 0}

    counts = labels.group_counts(con, did, 0.2, 0.05)
    assert counts == {"animal": 3, "empty": 1, "uncertain": 1, "human": 1}

    n = processing.build_events(con, did, 60)
    assert n == 4  # burst + 3 singles
    evs = labels.events_to_label(con, did, 0.2, 0.05)
    assert len(evs) == 3  # empty event excluded
    burst = evs[0]
    assert burst["n_files"] == 3

    zebra = db.add_species(con, "Plains zebra", "Equus quagga")
    impala = db.add_species(con, "Impala", "Aepyceros melampus")
    labels.set_event_labels(con, burst["id"], [(zebra, 4, ""), (impala, 2, "juveniles")], note="at waterhole")

    # override one file in the burst
    files = labels.event_media(con, burst["id"], 0.2, 0.05)
    labels.set_media_labels(con, files[2]["id"], [(impala, 1, "")])
    assert [l["common_name"] for l in labels.effective_labels(con, files[0]["id"])] == ["Impala", "Plains zebra"]
    assert [l["common_name"] for l in labels.effective_labels(con, files[2]["id"])] == ["Impala"]

    # rebuilding events is refused once labelled
    with pytest.raises(RuntimeError):
        processing.build_events(con, did, 60)

    # user rescues the empty file
    empty = labels.media_in_group(con, did, "empty", 0.2, 0.05)
    labels.set_manual_group(con, [empty[0]["id"]], "animal")
    assert labels.group_counts(con, did, 0.2, 0.05).get("empty") is None

    # time correction: +1 hour
    db.update_deployment(con, did, time_offset_seconds=3600)
    out = tmp_path / "out.csv"
    n_rows = export.export_project(con, pid, out)
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert n_rows == len(rows)
    first = rows[0]
    assert first["time"] == "07:00:00" and first["station"] == "CT01"
    assert {r["species"] for r in rows if r["file"].endswith("a0.jpg")} == {"Plains zebra", "Impala"}
    assert [r["count"] for r in rows if r["file"].endswith("a2.jpg")] == ["1"]

    xlsx = tmp_path / "out.xlsx"
    assert export.export_project(con, pid, xlsx) == n_rows


def test_thresholds_change_groups():
    assert grouping.classify(0.15, 0, 0, 0.2, 0.05) == "uncertain"
    assert grouping.classify(0.15, 0, 0, 0.1, 0.05) == "animal"
    assert grouping.classify(0.01, 0.0, 0.0) == "empty"
    assert grouping.classify(0.01, 0.0, 0.5) == "human"
    assert grouping.classify(None, None, None) is None
    assert grouping.classify(0.0, 0, 0, manual="animal") == "animal"


def test_species_import(tmp_path):
    con = db.connect(tmp_path / "s.db")
    p = tmp_path / "sp.csv"
    p.write_text("common name;scientific name\nLion;Panthera leo\nGrevy's zebra;Equus grevyi\n\n", encoding="utf-8")
    assert db.import_species_table(con, p) == 2
    assert [s["common_name"] for s in db.list_species(con)] == ["Grevy's zebra", "Lion"]


def test_postprocess_maps_boxes_back():
    img = np.zeros((480, 640, 3), np.uint8)
    blob, r, pad, hw = preprocess(img, 1280)
    assert blob.shape == (1, 3, 1280, 1280)
    # one animal box centred in the image, 200x100 px in original coordinates
    cx, cy = 320 * r + pad[0], 240 * r + pad[1]
    out = np.zeros((1, 2, 8), np.float32)
    out[0, 0] = [cx, cy, 200 * r, 100 * r, 0.9, 0.95, 0.01, 0.01]
    out[0, 1] = [cx + 1, cy, 200 * r, 100 * r, 0.8, 0.9, 0.01, 0.01]  # duplicate -> NMS
    dets = postprocess(out, r, pad, hw)
    assert len(dets) == 1 and dets[0].category == "animal"
    x1, y1, x2, y2 = dets[0].box
    assert abs(x1 - 220 / 640) < 0.01 and abs(y2 - 290 / 480) < 0.01


def test_video_sampling(tmp_path):
    cv2 = pytest.importorskip("cv2")
    from ctt.media import sample_video_frames

    path = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    if not w.isOpened():
        pytest.skip("no video encoder")
    for i in range(35):
        w.write(np.full((48, 64, 3), 200 if i >= 20 else 0, np.uint8))
    w.release()
    frames = list(sample_video_frames(path, 1.0))
    assert [round(t) for t, _ in frames] == [0, 1, 2, 3]


def test_sort_into_subfolders(setup, tmp_path):
    from ctt import sorting

    con, pid, did, folder = setup
    processing.scan_deployment(con, did)
    processing.run_detection(con, did, FakeDetector())
    processing.build_events(con, did, 60)
    goat = db.add_species(con, "Goat", "Capra hircus", "Domestic")
    zebra = db.add_species(con, "Zebra", "", "Ungulates")
    evs = labels.events_to_label(con, did, 0.2, 0.05)
    labels.set_event_labels(con, evs[0]["id"], [(goat, 3, "")])      # animal burst, but goats
    labels.set_event_labels(con, evs[1]["id"], [(zebra, 1, "")])     # uncertain file labelled zebra
    res = sorting.copy_sorted(con, did)
    assert res["counts"] == {"Wildlife": 1, "People & livestock": 4, "Empty": 1, "Uncertain": 0}
    out = folder / "CTT_Sorted"
    assert (out / "People & livestock" / "a0.jpg").exists()
    assert (out / "Wildlife" / "u0.jpg").exists()
    assert (folder / "a0.jpg").exists()                                # originals untouched
    assert processing.scan_deployment(con, did) == 0                   # copies not re-scanned
    again = sorting.copy_sorted(con, did)
    assert again["skipped"] == 6
