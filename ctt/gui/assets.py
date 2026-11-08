"""Locate bundled image files (logo, icon) both in development and in the packed app."""

import sys
from pathlib import Path


def asset_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "assets" / name
