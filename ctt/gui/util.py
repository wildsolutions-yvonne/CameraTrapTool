"""Small helpers shared by the GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QImage, QImageReader
from PySide6.QtWidgets import QMessageBox


def bgr_to_qimage(bgr) -> QImage:
    h, w = bgr.shape[:2]
    rgb = bgr[:, :, ::-1].copy()
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def load_image(path: str | Path, kind: str = "image", seconds: float | None = None, max_side: int | None = None) -> QImage:
    """Load an image (or a video frame) as QImage, optionally scaled down."""
    if kind == "video":
        from ctt.media import video_frame_at

        frame = video_frame_at(path, seconds or 0.0)
        if frame is None:
            return QImage()
        img = bgr_to_qimage(frame)
    else:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if max_side:
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > max_side:
                size.scale(max_side, max_side, _keep())
                reader.setScaledSize(size)
        img = reader.read()
    if max_side and not img.isNull() and max(img.width(), img.height()) > max_side:
        from PySide6.QtCore import Qt

        img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


def _keep():
    from PySide6.QtCore import Qt

    return Qt.AspectRatioMode.KeepAspectRatio


def open_file(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def error(parent, title, exc):
    QMessageBox.critical(parent, title, str(exc))


def confirm(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes
