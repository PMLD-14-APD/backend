"""Pembungkus model deteksi. Bagian lain hanya tahu `Detector.detect(frame)`,
jadi backend model bisa diganti (YOLO, ONNX, dll) tanpa menyentuh logika kepatuhan."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import settings


@dataclass
class Detection:
    label: str                                   # nama kelas, mis. "person", "helmet"
    conf: float
    box: tuple[float, float, float, float]       # x1, y1, x2, y2 (piksel)


class Detector(Protocol):
    def detect(self, frame) -> list[Detection]: ...


def resolve_weights(weights_path: str) -> Path:
    """Path absolut / yang sudah ada dipakai apa adanya; selain itu dicari di MODELS_DIR."""
    p = Path(weights_path)
    return p if p.is_absolute() or p.exists() else Path(settings.models_dir) / weights_path


class YoloDetector:
    def __init__(self, weights_path: str, conf: float):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Paket 'ultralytics' belum terpasang. Jalankan: pip install ultralytics") from exc
        path = resolve_weights(weights_path)
        if not path.exists():
            raise RuntimeError(f"File bobot model tidak ditemukan: {path}")
        self.model = YOLO(str(path))
        self.conf = conf

    def detect(self, frame) -> list[Detection]:
        result = self.model.predict(frame, conf=self.conf, verbose=False)[0]
        names = result.names
        return [
            Detection(names[int(b.cls[0])], float(b.conf[0]), tuple(float(v) for v in b.xyxy[0].tolist()))
            for b in result.boxes
        ]


def load_detector(weights_path: str) -> Detector:
    return YoloDetector(weights_path, settings.inference_conf)