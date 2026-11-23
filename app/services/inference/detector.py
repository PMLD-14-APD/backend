"""Pembungkus model deteksi. Bagian lain hanya tahu `Detector.detect(frame)`,
jadi backend model bisa diganti (YOLO, ONNX, dll) tanpa menyentuh logika kepatuhan."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import settings


CROP_PADDING = 0.15
CROP_TARGET = 640
CONF_FLOOR = 0.05
OPPOSITE_CLASS = {
    "Hardhat": "NO-Hardhat",
    "NO-Hardhat": "Hardhat",
    "Safety Vest": "NO-Safety Vest",
    "NO-Safety Vest": "Safety Vest",
}
POSITIVE_CLASSES = {"Hardhat", "Safety Vest"}


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


def _load_yolo(weights_path: str):
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Paket 'ultralytics' belum terpasang. Jalankan: pip install ultralytics") from exc
    path = resolve_weights(weights_path)
    if not path.exists():
        raise RuntimeError(f"File bobot model tidak ditemukan: {path}")
    return YOLO(str(path))


def _predict_boxes(
    model,
    image,
    conf: float,
    imgsz: int | None = None,
    classes: list[int] | None = None,
    offset: tuple[int, int] = (0, 0),
    scale: float = 1.0,
) -> list[Detection]:
    kwargs = {"conf": conf, "verbose": False}
    if imgsz is not None:
        kwargs["imgsz"] = imgsz
    if classes is not None:
        kwargs["classes"] = classes
    result = model.predict(image, **kwargs)[0]
    names = result.names
    ox, oy = offset
    return [
        Detection(
            names[int(b.cls[0])],
            float(b.conf[0]),
            (
                b.xyxy[0][0] / scale + ox,
                b.xyxy[0][1] / scale + oy,
                b.xyxy[0][2] / scale + ox,
                b.xyxy[0][3] / scale + oy,
            )
            if scale != 1.0 or ox or oy
            else tuple(float(v) for v in b.xyxy[0].tolist()),
        )
        for b in result.boxes
    ]


def filter_person_detections(
    detections: list[Detection],
    frame_height: int,
    person_label: str,
    min_conf: float,
    min_height_ratio: float,
) -> list[Detection]:
    kept = []
    for d in detections:
        if d.conf < min_conf:
            continue
        if frame_height > 0 and (d.box[3] - d.box[1]) / frame_height < min_height_ratio:
            continue
        kept.append(Detection(person_label, d.conf, tuple(float(v) for v in d.box)))
    return kept


def compute_crop_rect(box: tuple, frame_w: int, frame_h: int, padding: float = CROP_PADDING) -> tuple[int, int, int, int]:
    bw = box[2] - box[0]
    bh = box[3] - box[1]
    return (
        max(0, int(box[0] - padding * bw)),
        max(0, int(box[1] - padding * bh)),
        min(frame_w, int(box[2] + padding * bw)),
        min(frame_h, int(box[3] + padding * bh)),
    )


def _overlap_metrics(a: tuple, b: tuple) -> tuple[float, float]:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (area_a + area_b - inter + 1e-9), inter / min(area_a, area_b)


def select_final_ppe(
    detections: list[Detection],
    class_confs: dict[str, float],
    default_conf: float,
) -> list[Detection]:
    filtered = [d for d in detections if d.conf >= class_confs.get(d.label, default_conf)]
    filtered.sort(key=lambda d: -(d.conf + (0.05 if d.label in POSITIVE_CLASSES else 0.0)))

    kept: list[Detection] = []
    for cand in filtered:
        opp = OPPOSITE_CLASS.get(cand.label)
        drop = False
        for prev in kept:
            iou, ios = _overlap_metrics(cand.box, prev.box)
            if cand.label == prev.label and (iou > 0.50 or ios > 0.65):
                drop = True
                break
            if prev.label == opp and (iou >= 0.45 or ios >= 0.55):
                prev_score = prev.conf + (0.05 if prev.label in POSITIVE_CLASSES else 0.0)
                cand_score = cand.conf + (0.05 if cand.label in POSITIVE_CLASSES else 0.0)
                if prev_score >= cand_score:
                    drop = True
                    break
        if not drop:
            kept.append(cand)
    return kept


def _class_confs_from_settings() -> dict[str, float]:
    return {
        "Hardhat": settings.hardhat_conf,
        "Safety Vest": settings.vest_conf,
        "NO-Hardhat": 0.10,
        "NO-Safety Vest": 0.20,
    }


class YoloDetector:
    def __init__(self, weights_path: str, conf: float):
        self.model = _load_yolo(weights_path)
        self.conf = conf

    def detect(self, frame) -> list[Detection]:
        detections = _predict_boxes(self.model, frame, conf=self.conf)
        target_lower = settings.person_label.lower()
        return [
            Detection(settings.person_label, d.conf, d.box) if d.label.lower() == target_lower else d
            for d in detections
        ]


class TwoStageYoloDetector:
    def __init__(self, ppe_weights_path: str, person_weights_path: str):
        self.ppe_model = _load_yolo(ppe_weights_path)
        self.person_model = _load_yolo(person_weights_path)

    def detect(self, frame) -> list[Detection]:
        import cv2

        frame_h, frame_w = frame.shape[:2]
        raw_persons = _predict_boxes(self.person_model, frame, conf=settings.person_conf, classes=[0])
        persons = filter_person_detections(
            raw_persons,
            frame_h,
            settings.person_label,
            settings.person_conf,
            settings.min_person_height_ratio,
        )

        raw_ppe = _predict_boxes(self.ppe_model, frame, conf=CONF_FLOOR)
        for p in persons:
            x1, y1, x2, y2 = compute_crop_rect(p.box, frame_w, frame_h)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            scale = CROP_TARGET / max(crop.shape[:2])
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
            resized = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=interp)
            raw_ppe.extend(
                _predict_boxes(
                    self.ppe_model,
                    resized,
                    conf=CONF_FLOOR,
                    imgsz=CROP_TARGET,
                    offset=(x1, y1),
                    scale=scale,
                )
            )

        person_lower = settings.person_label.lower()
        ppe_only = [d for d in raw_ppe if d.label.lower() != person_lower]
        final_ppe = select_final_ppe(ppe_only, _class_confs_from_settings(), settings.inference_conf)
        return [*persons, *final_ppe]


def load_detector(weights_path: str) -> Detector:
    person_weights = settings.person_weights_path.strip()
    if person_weights:
        return TwoStageYoloDetector(weights_path, person_weights)
    return YoloDetector(weights_path, settings.inference_conf)