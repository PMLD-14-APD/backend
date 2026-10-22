"""Tracker IoU sederhana: memberi ID yang sama untuk orang yang sama antar frame."""
from dataclasses import dataclass


def iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    id: int
    box: tuple
    last_seen: int


class IouTracker:
    def __init__(self, iou_threshold: float = 0.3, max_age: int = 15):
        self.iou_threshold = iou_threshold
        self.max_age = max_age          # dalam jumlah frame yang diproses
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, boxes: list, frame_idx: int) -> list[int]:
        """Return track id untuk tiap box (urutan sama dengan `boxes`)."""
        pairs = sorted(
            ((iou(t.box, b), tid, bi) for tid, t in self.tracks.items() for bi, b in enumerate(boxes)),
            reverse=True,
        )
        assigned: dict[int, int] = {}
        used_tracks: set[int] = set()
        for score, tid, bi in pairs:
            if score < self.iou_threshold:
                break
            if bi in assigned or tid in used_tracks:
                continue
            assigned[bi] = tid
            used_tracks.add(tid)

        ids = []
        for bi, box in enumerate(boxes):
            tid = assigned.get(bi)
            if tid is None:
                tid = self._next_id
                self._next_id += 1
                self.tracks[tid] = Track(tid, box, frame_idx)
            else:
                self.tracks[tid].box = box
                self.tracks[tid].last_seen = frame_idx
            ids.append(tid)

        for tid in [t for t, tr in self.tracks.items() if frame_idx - tr.last_seen > self.max_age]:
            del self.tracks[tid]
        return ids