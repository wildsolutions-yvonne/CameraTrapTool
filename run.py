"""Start Trapster (by Wildsolutions)."""

import sys


def selftest(out_path, sample_image=None):
    """Used by the build: check the packed .exe really works, write a report, exit 0/1."""
    import os
    import tempfile
    import traceback

    lines, ok = [], True

    def step(name, fn):
        nonlocal ok
        try:
            res = fn()
            lines.append(f"OK   {name}" + (f": {res}" if res is not None else ""))
        except Exception:
            ok = False
            lines.append(f"FAIL {name}\n{traceback.format_exc()}")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # the offscreen platform has no fonts of its own: point it at the Windows fonts
    windir = os.environ.get("WINDIR")
    if windir and os.path.isdir(os.path.join(windir, "Fonts")):
        os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(windir, "Fonts"))
    step("numpy", lambda: __import__("numpy").__version__)
    step("opencv", lambda: __import__("cv2").__version__)
    step("onnxruntime", lambda: __import__("onnxruntime").get_available_providers())
    step("openpyxl", lambda: __import__("openpyxl").__version__)
    step("matplotlib qt", lambda: __import__("matplotlib.backends.backend_qtagg", fromlist=["x"]) and None)

    def detector():
        from ctt.detector import MegaDetector
        from ctt.media import read_image_bgr

        res = []
        for gpu in (False, True):
            det = MegaDetector(prefer_gpu=gpu)
            if sample_image:
                best = max((d.confidence for d in det.detect(read_image_bgr(sample_image)) if d.category == "person"), default=0)
                if best < 0.5:
                    raise RuntimeError(f"person not found ({best:.2f}) on {det.device_label}")
                res.append(f"{det.device_label} person={best:.2f}")
            else:
                res.append(det.device_label)
        return "; ".join(res)

    step("MegaDetector", detector)

    def gui():
        import datetime as dt

        from PIL import Image
        from PySide6.QtWidgets import QApplication

        from ctt import db, labels, processing
        from ctt.gui import theme
        from ctt.gui.dialogs import ProjectDialog, SpeciesDialog, StationDialog
        from ctt.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(theme.style_sheet())
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "t.db")
        folder = os.path.join(tmp, "DCIM")
        os.makedirs(folder)
        t0 = dt.datetime(2026, 3, 1, 6)
        for i in range(4):
            im = Image.new("RGB", (64, 48), (200, 200, 200))
            ex = Image.Exif()
            ex[0x0132] = (t0 + dt.timedelta(hours=5 * i)).strftime("%Y:%m:%d %H:%M:%S")
            im.save(os.path.join(folder, f"img{i}.jpg"), exif=ex)
        con = db.connect(path)
        pid = db.add_project(con, "Test", location="Laikipia")
        sid = db.add_station(con, pid, "CT01", -0.5, 37.0, elevation=1800)
        did = db.add_deployment(con, sid, "Dep1", folder, "2026-03-01", "2026-03-10")
        lion = db.add_species(con, "Lion", "Panthera leo", "Carnivores")
        hy = db.add_species(con, "Spotted hyena", "Crocuta crocuta", "Carnivores")
        processing.scan_deployment(con, did)
        con.executemany("UPDATE media SET max_animal=?, max_person=0, max_vehicle=0 WHERE relpath=?",
                        [(0.9, "img0.jpg"), (0.8, "img1.jpg"), (0.01, "img2.jpg"), (0.1, "img3.jpg")])
        con.commit()
        processing.build_events(con, did, 60)
        evs = labels.events_to_label(con, did, 0.2, 0.05)
        labels.set_event_labels(con, evs[0]["id"], [(lion, 2, "")])
        labels.set_event_labels(con, evs[1]["id"], [(hy, 1, "")])
        con.close()
        shots = os.environ.get("CTT_SCREENSHOTS")

        def shot(widget, name, wait_ms=0):
            if not shots:
                return
            if wait_ms:
                from PySide6.QtCore import QEventLoop, QTimer

                loop = QEventLoop()
                QTimer.singleShot(wait_ms, loop.quit)
                loop.exec()
            app.processEvents()
            os.makedirs(shots, exist_ok=True)
            widget.grab().save(os.path.join(shots, f"{name}.png"))

        con = db.connect(path)
        db.update_project(con, pid, notes="Primate camera trap survey")
        sid2 = db.add_station(con, pid, "CT02", -0.49, 37.03, elevation=1750)
        db.add_project(con, "Sibiloi 2026", location="Turkana, Kenya")
        for name, sci, grp in (("Olive baboon", "Papio anubis", "Primates"), ("Goat", "Capra hircus", "Domestic"),
                               ("Kirk's dik-dik", "Madoqua kirkii", "Ungulates")):
            db.add_species(con, name, sci, grp)
        con.close()
        win = MainWindow(path)
        win.resize(1500, 920)
        win.show()
        app.processEvents()
        shot(win, "1_home")
        assert len(win.home.cards) == 3, "home page should show 1 project + 'new' card"
        win.open_project(pid)
        app.processEvents()
        page = win.project_page
        shot(win, "2_dashboard_map", 6000)
        for i in range(page.taxon.count()):
            page.taxon.setCurrentIndex(i)
            for k in range(page.charts.kind.count()):
                page.charts.kind.setCurrentIndex(k)
                app.processEvents()
        page.taxon.setCurrentIndex(0)
        page.tabs.setCurrentIndex(1)
        page.charts.kind.setCurrentText("Activity overlap of two species")
        shot(win, "3_dashboard_chart")
        for i in range(page.tabs.count()):
            page.tabs.setCurrentIndex(i)
            app.processEvents()
            if i == 2:
                shot(win, "4_dashboard_stations")
        win._select(("station", sid))
        app.processEvents()
        shot(win, "5_station")
        win._select(("deployment", did))
        app.processEvents()
        dp = win.deployment_page
        shot(win, "6_deployment_grid", 1500)
        dp.tabs.setCurrentIndex(1)
        app.processEvents()
        dp.labeller.picker.search.setText("hy")
        app.processEvents()
        assert dp.labeller.picker.list.count() == 1, "species search should find hyena only"
        dp.labeller.picker.search.clear()
        app.processEvents()
        shot(win, "7_labeller", 1500)
        n_before = dp.labeller.event_list.count()
        dp.labeller.event_list.setCurrentRow(n_before - 1)
        dp.labeller.quick_buttons["team"].click()
        app.processEvents()
        assert dp.labeller.event_list.count() == n_before - 1, "quick-labelled event should leave the list"
        dp.tabs.setCurrentIndex(0)
        dp.grid.group.setCurrentIndex(dp.grid.group.findData("team"))
        app.processEvents()
        assert dp.grid.list.count() >= 1, "survey team file should be in the team view"
        shot(win, "7b_grid_team", 1000)
        assert "★" in dp.labeller.picker.list.item(0).text(), "recent species should be on top"
        from ctt.gui.deployment_page import ProgressTracker, fmt_duration

        tr = ProgressTracker()
        for d in range(1, 5):
            tr.update(d, 100)
        assert fmt_duration(3725) == "1 h 02 min"
        con = db.connect(path)
        st_row = con.execute("SELECT * FROM station WHERE id=?", (sid,)).fetchone()
        others = db.list_stations(con, pid)
        for name, dlg in (("8_project_dialog", ProjectDialog(win)),
                          ("9_station_dialog", StationDialog(win, st_row, others)),
                          ("10_species_list", SpeciesDialog(win, win.con))):
            dlg.show()
            app.processEvents()
            shot(dlg, name, 5000 if "station" in name else 0)
            dlg.close()
        # dashboard: clickable tiles, deployments tab, species footage gallery
        win._select(("project", pid))
        app.processEvents()
        page.tiles["records"].clicked.emit()
        assert page.tabs.tabText(page.tabs.currentIndex()) == "Species"
        page.tiles["trapnights"].clicked.emit()
        assert page.tabs.tabText(page.tabs.currentIndex()) == "Deployments"
        assert page.dep_table.rowCount() >= 1
        shot(win, "11_deployments_tab")
        from ctt.gui.gallery import FootageGallery

        gal = FootageGallery(win, win.con, pid, "Lion", {"Lion"})
        gal.show()
        app.processEvents()
        assert gal.list.count() == 1, f"lion footage expected 1, got {gal.list.count()}"
        shot(gal, "12_species_gallery", 1500)
        gal.list.setCurrentRow(0)
        gal._goto()
        app.processEvents()
        assert win.pages.currentWidget() is win.deployment_page
        win.go_home()
        app.processEvents()
        win.close()
        return ("home, dashboard (all charts/tabs/taxa, tiles, deployments), station, deployment, labeller search, "
                "quick labels, species gallery + jump to event, dialogs")

    step("GUI", gui)

    def network():
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QSslSocket
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        out = [f"TLS backends {QSslSocket.availableBackends()}"]
        nam = QNetworkAccessManager()
        for url in ("https://tile.openstreetmap.org/10/616/515.png",
                    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/10/515/616",
                    "https://api.open-meteo.com/v1/elevation?latitude=0.123&longitude=37.04"):
            req = QNetworkRequest(QUrl(url))
            req.setRawHeader(b"User-Agent", b"Trapster selftest")
            reply = nam.get(req)
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            QTimer.singleShot(20000, loop.quit)
            loop.exec()
            n = len(bytes(reply.readAll()))
            if reply.error() != reply.NetworkError.NoError or n < 10:
                raise RuntimeError(f"{url}: {reply.errorString()} ({n} bytes)")
            out.append(f"{url.split('/')[2]} {n} B")
        return "; ".join(out)

    step("Map tiles + elevation over the network", network)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\nALL OK\n" if ok else "\nSELFTEST FAILED\n"))
    sys.exit(0 if ok else 1)


def log_dir():
    import os
    from pathlib import Path

    d = Path(os.environ.get("APPDATA") or Path.home()) / "CameraTrapTool" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging():
    """Write everything that goes wrong to %APPDATA%\\CameraTrapTool\\logs."""
    import datetime as dt
    import faulthandler
    import logging
    import threading
    import traceback

    d = log_dir()
    logfile = d / "cameratraptool.log"
    logging.basicConfig(
        filename=str(logfile), level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Hard crashes (inside C libraries) are written here by faulthandler.
    crash = open(d / "crash.log", "a", encoding="utf-8")
    crash.write(f"\n=== started {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
    crash.flush()
    faulthandler.enable(crash, all_threads=True)
    # A windowed app has no console: give Python a place to print.
    if sys.stdout is None:
        sys.stdout = open(d / "stdout.log", "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = crash

    def excepthook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        logging.error("Unhandled error:\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance():
                QMessageBox.critical(
                    None, "Trapster - error",
                    f"Something went wrong:\n\n{value}\n\nDetails were saved in:\n{logfile}\n\n"
                    "Your data is safe. Please send that file to the developer.",
                )
        except Exception:
            pass

    sys.excepthook = excepthook
    threading.excepthook = lambda a: excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    import platform

    from ctt import __version__

    logging.info("Trapster %s on %s, Python %s", __version__, platform.platform(), platform.python_version())
    return logfile


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    setup_logging()
    import logging

    from PySide6.QtWidgets import QApplication

    from ctt.gui.main_window import MainWindow

    from PySide6.QtGui import QIcon

    from ctt.gui import theme
    from ctt.gui.assets import asset_path

    if sys.platform == "win32":  # own taskbar icon instead of the Python one
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wildsolutions.Trapster")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Trapster")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.style_sheet())
    app.setWindowIcon(QIcon(str(asset_path("app.ico"))))
    win = MainWindow()
    win.show()
    logging.info("Window shown")
    code = app.exec()
    logging.info("Closed normally (code %s)", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
