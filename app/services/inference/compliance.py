"""Logika kepatuhan APD (murni, tanpa DB/OpenCV, jadi gampang dites).

Kontrak model: keluaran berisi kelas `person` + satu kelas per APD dengan nama
sama persis dengan `apd_classes.label_key` (mis. helmet, vest).
APD dianggap dipakai orang itu bila titik tengah box APD ada di dalam box orang."""
from dataclasses import dataclass, field

from app.services.inference.detector import Detection

LENGKAP, KURANG, TIDAK = "lengkap", "kurang_lengkap", "tidak_digunakan"
RANK = {LENGKAP: 0, KURANG: 1, TIDAK: 2}   # makin besar makin parah


@dataclass
class PersonResult:
    box: tuple
    conf: float
    present: dict[str, float] = field(default_factory=dict)   # label_key -> confidence
    status: str = LENGKAP
    missing: list[str] = field(default_factory=list)


def _center_inside(box, outer) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _area(b) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def evaluate(detections: list[Detection], required: list[str], person_label: str) -> list[PersonResult]:
    """`required` = label_key APD wajib di environment. Return satu hasil per orang."""
    persons = [PersonResult(box=d.box, conf=d.conf) for d in detections if d.label == person_label]

    for d in detections:
        if d.label not in required:
            continue
        owners = [p for p in persons if _center_inside(d.box, p.box)]
        if not owners:
            continue
        owner = min(owners, key=lambda p: _area(p.box))     # orang terkecil yang memuat = paling spesifik
        if d.conf > owner.present.get(d.label, 0.0):
            owner.present[d.label] = d.conf

    for p in persons:
        p.missing = [k for k in required if k not in p.present]
        if not p.missing:
            p.status = LENGKAP
        elif not p.present:
            p.status = TIDAK
        else:
            p.status = KURANG
    return persons