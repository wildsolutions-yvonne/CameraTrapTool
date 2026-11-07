"""Finding camera trap files, reading their timestamps, and sampling video frames."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".wmv", ".mts"}


def find_media(folder: str | Path):
    """Yield (relative_path, kind) for every image/video under folder, sorted."""
    folder = Path(folder)
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            ext = Path(name).suffix.lower()
            if ext in IMAGE_EXT:
                kind = "image"
            elif ext in VIDEO_EXT:
                kind = "video"
            else:
                continue
            rel = os.path.relpath(os.path.join(root, name), folder)
            found.append((rel.replace("\\", "/"), kind))
    found.sort()
    return found


def _parse_exif_dt(value) -> dt.datetime | None:
    if not value:
        return None
    value = str(value).strip().replace("\x00", "")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            return dt.datetime.strptime(value[:19], fmt)
        except ValueError:
            pass
    return None


def image_timestamp(path: str | Path) -> dt.datetime | None:
    """DateTimeOriginal from EXIF, else file modified time."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            exif = im.getexif()
            # 0x8769 = Exif IFD, 0x9003 = DateTimeOriginal, 0x0132 = DateTime
            sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
            stamp = _parse_exif_dt(sub.get(0x9003)) or _parse_exif_dt(exif.get(0x0132))
            if stamp:
                return stamp
    except Exception:
        pass
    return file_timestamp(path)


def file_timestamp(path: str | Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0)
    except OSError:
        return None


def video_timestamp(path: str | Path) -> dt.datetime | None:
    # Camera trap videos rarely carry reliable metadata readable without ffprobe;
    # the file modified time is what most trail cameras set to the recording time.
    return file_timestamp(path)


def sample_video_frames(path: str | Path, every_seconds: float = 1.0, max_frames: int = 120):
    """Yield (seconds, BGR frame) roughly every `every_seconds` through the video."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"Could not open video: {path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if fps <= 0 or fps > 1000:
            fps = 25.0
        step = max(1, int(round(fps * every_seconds)))
        idx = 0
        yielded = 0
        while yielded < max_frames:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    yield idx / fps, frame
                    yielded += 1
            idx += 1
    finally:
        cap.release()


def read_image_bgr(path: str | Path):
    """Read an image as a BGR numpy array (handles non-ASCII Windows paths)."""
    import cv2
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise IOError(f"Could not read image: {path}")
    return img


def video_frame_at(path: str | Path, seconds: float):
    """Return the BGR frame nearest to `seconds` (for thumbnails/preview)."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()
