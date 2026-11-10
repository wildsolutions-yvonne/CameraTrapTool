# Trapster by Wildsolutions

A simple Windows tool for camera trap data, inspired by AddaxAI:

1. **Find empty files.** MegaDetector v5a checks every photo, and about one frame per second of each video. Each file goes into one of four groups: **Animal**, **Uncertain**, **Human / Vehicle** or **Empty**.
2. **Check the empty files** in a thumbnail grid and rescue any file that does have an animal.
3. **Label animals by hand.** Photos taken close together are grouped into *events*. Each event gets one or more species from your master list, a count for each species and a note. You can override the label for a single file.
4. **Export** everything to Excel or CSV, with project, station, GPS, deployment, corrected date/time, species, count and notes.

Your original image and video files are **never moved, renamed or changed**. Everything is stored in one database file at `%APPDATA%\CameraTrapTool\cameratraptool.db`. Back up that file to keep your labels safe.

## Structure

- **Project**, e.g. "Laikipia 2026". Holds the detection thresholds and the event time gap.
- **Station**: a camera location, with GPS coordinates.
- **Deployment**: one camera visit. It has a folder of files, start and end dates, a camera ID and an optional time correction.

The project dashboard shows a map of the stations (when online), a per-station table and summary charts: events per species, events per station and activity by hour.

## Installing

Download the newest `Trapster-portable-*.zip (or Trapster-Setup-*.exe)` from the repository's **Releases** page, or from the latest **Actions** run under *Artifacts*. Then double-click it. You don't need administrator rights.

The detector uses your graphics card through DirectML (Intel Arc, AMD, NVIDIA) when it can, and the normal processor otherwise.

## Thresholds

| Group | Rule (defaults) |
|---|---|
| Animal | animal confidence ≥ 0.20 |
| Human / Vehicle | person or vehicle confidence ≥ 0.20, and no animal ≥ 0.20 |
| Uncertain | highest confidence between 0.05 and 0.20 |
| Empty | everything below 0.05 |

You can change the thresholds for each project. The groups update instantly, without re-running the detector.

## Developers

```
pip install -r requirements.txt pytest
python -m pytest tests
python run.py
```

`.github/workflows/build.yml` converts MegaDetector to ONNX, runs the tests, bundles the app with PyInstaller and builds the installer with Inno Setup. To publish a release, push a tag such as `v0.1.0`.

## Credits

- MegaDetector: Beery, Morris & Yang (2019), *Efficient pipeline for camera trap image review*, arXiv:1907.06772.
- AddaxAI: van Lunteren (2023), *JOSS* 8(88), 5581.
