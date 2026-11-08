"""Start Camera Trap Tool."""

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
        from PySide6.QtWidgets import QApplication
        from ctt.gui.main_window import MainWindow
        from ctt import db

        app = QApplication.instance() or QApplication([])
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        con = db.connect(path)
        pid = db.add_project(con, "Test")
        sid = db.add_station(con, pid, "CT01", -0.5, 37.0)
        did = db.add_deployment(con, sid, "Dep1", tempfile.mkdtemp())
        db.add_species(con, "Lion", "Panthera leo")
        con.close()
        win = MainWindow(path)
        win.show()
        for kind, rid in (("project", pid), ("station", sid), ("deployment", did)):
            win.refresh_tree((kind, rid))
            app.processEvents()
        win.deployment_page.tabs.setCurrentIndex(1)
        app.processEvents()
        win.close()
        return "window, dashboard, station page, deployment page, labeller opened"

    step("GUI", gui)
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
                    None, "Camera Trap Tool - error",
                    f"Something went wrong:\n\n{value}\n\nDetails were saved in:\n{logfile}\n\n"
                    "Your data is safe. Please send that file to the developer.",
                )
        except Exception:
            pass

    sys.excepthook = excepthook
    threading.excepthook = lambda a: excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    import platform

    from ctt import __version__

    logging.info("Camera Trap Tool %s on %s, Python %s", __version__, platform.platform(), platform.python_version())
    return logfile


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    setup_logging()
    import logging

    from PySide6.QtWidgets import QApplication

    from ctt.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Camera Trap Tool")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    logging.info("Window shown")
    code = app.exec()
    logging.info("Closed normally (code %s)", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
