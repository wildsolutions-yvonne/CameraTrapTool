"""Build-time helper: check the exported MegaDetector ONNX model on a sample image.

The export itself runs in GitHub Actions (see .github/workflows/build.yml):
  1. clone ultralytics/yolov5 at the commit MegaDetector v5 was trained with
  2. download md_v5a.0.0.pt from the MegaDetector release
  3. python export.py --weights md_v5a.0.0.pt --include onnx --imgsz 1280
This script then loads the ONNX file with our own detector code and checks that
it finds the people in yolov5's sample photo, proving pre/post-processing match.

Usage: python tools/export_megadetector_onnx.py MODEL.onnx SAMPLE.jpg
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctt.detector import MegaDetector  # noqa: E402
from ctt.media import read_image_bgr  # noqa: E402


def main(model, sample):
    det = MegaDetector(model, prefer_gpu=False)
    dets = det.detect(read_image_bgr(sample))
    for d in dets[:10]:
        print(f"{d.category:8s} {d.confidence:.3f} {tuple(round(x, 3) for x in d.box)}")
    best_person = max((d.confidence for d in dets if d.category == "person"), default=0)
    print("best person score:", best_person)
    if best_person < 0.5:
        raise SystemExit("Sanity check FAILED: MegaDetector did not find the person in the sample image")
    print("Sanity check passed")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
