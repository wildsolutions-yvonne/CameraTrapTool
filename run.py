"""Start Camera Trap Tool."""

import sys


def main():
    from PySide6.QtWidgets import QApplication

    # QtWebEngine (station map) must be imported before the QApplication exists.
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except Exception:
        pass
    from ctt.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Camera Trap Tool")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
