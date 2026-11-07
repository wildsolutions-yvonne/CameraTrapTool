"""MegaDetector (v5a, YOLOv5 architecture) running through ONNX Runtime.

The ONNX file is created at build time by tools/export_megadetector_onnx.py and
shipped inside the installer as models/md_v5a.onnx.

Execution providers are tried in this order:
  DirectML (any DirectX 12 GPU, incl. Intel Arc)  ->  CPU
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CATEGORIES = {0: "animal", 1: "person", 2: "vehicle"}
INPUT_SIZE = 1280  # MegaDetector v5 was trained at 1280 px


@dataclass
class Detection:
    category: str
    confidence: float
    box: tuple  # x1, y1, x2, y2 normalised 0..1


def default_model_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "models" / "md_v5a.onnx"


class MegaDetector:
    def __init__(self, model_path: str | Path | None = None, prefer_gpu: bool = True):
        import onnxruntime as ort

        model_path = Path(model_path or default_model_path())
        if not model_path.exists():
            raise FileNotFoundError(f"MegaDetector model not found: {model_path}")
        available = ort.get_available_providers()
        providers = []
        if prefer_gpu and "DmlExecutionProvider" in available:
            providers.append("DmlExecutionProvider")
        providers.append("CPUExecutionProvider")
        opts = ort.SessionOptions()
        try:
            self.session = ort.InferenceSession(str(model_path), opts, providers=providers)
        except Exception:
            # GPU initialisation can fail on old drivers; fall back to CPU.
            self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.provider = self.session.get_providers()[0]
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        self.size = shape[-1] if isinstance(shape[-1], int) else INPUT_SIZE
        self.fp16 = "float16" in inp.type

    @property
    def device_label(self) -> str:
        return "Graphics card (DirectML)" if self.provider == "DmlExecutionProvider" else "Processor (CPU)"

    def detect(self, bgr: np.ndarray, min_conf: float = 0.01) -> list[Detection]:
        blob, ratio, pad, (h, w) = preprocess(bgr, self.size)
        if self.fp16:
            blob = blob.astype(np.float16)
        out = self.session.run(None, {self.input_name: blob})[0]
        return postprocess(out, ratio, pad, (h, w), min_conf)


def letterbox(img: np.ndarray, size: int):
    import cv2

    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top = (size - nh) // 2
    left = (size - nw) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top : top + nh, left : left + nw] = resized
    return canvas, r, (left, top)


def preprocess(bgr: np.ndarray, size: int = INPUT_SIZE):
    h, w = bgr.shape[:2]
    canvas, r, pad = letterbox(bgr, size)
    rgb = canvas[:, :, ::-1]
    blob = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    return blob, r, pad, (h, w)


def postprocess(out, ratio, pad, orig_hw, min_conf=0.01, iou=0.45) -> list[Detection]:
    """YOLOv5 output [1, N, 5+C] -> detections with normalised boxes."""
    pred = np.asarray(out, dtype=np.float32)[0]
    if pred.size == 0:
        return []
    obj = pred[:, 4:5]
    cls_scores = pred[:, 5:] * obj
    cls = cls_scores.argmax(1)
    conf = cls_scores.max(1)
    keep = conf >= min_conf
    pred, cls, conf = pred[keep], cls[keep], conf[keep]
    if len(conf) == 0:
        return []
    xy, wh = pred[:, :2], pred[:, 2:4]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], axis=1)
    boxes[:, [0, 2]] -= pad[0]
    boxes[:, [1, 3]] -= pad[1]
    boxes /= ratio
    h, w = orig_hw
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w) / w
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h) / h
    result = []
    for c in np.unique(cls):
        idx = np.where(cls == c)[0]
        for i in nms(boxes[idx], conf[idx], iou):
            j = idx[i]
            result.append(Detection(CATEGORIES.get(int(c), str(int(c))), float(conf[j]), tuple(map(float, boxes[j]))))
    result.sort(key=lambda d: -d.confidence)
    return result


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        ious = inter / np.maximum(area_i + area_r - inter, 1e-9)
        order = rest[ious <= iou_thr]
    return keep


def max_scores(dets: list[Detection]) -> dict:
    s = {"animal": 0.0, "person": 0.0, "vehicle": 0.0}
    for d in dets:
        if d.category in s and d.confidence > s[d.category]:
            s[d.category] = d.confidence
    return s
