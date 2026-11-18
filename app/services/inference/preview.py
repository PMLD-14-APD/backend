"""Tayangan langsung beranotasi (fitur "perbesar"): frame terakhir yang sudah diinferensi beserta
kotak tiap orang. Hijau = APD lengkap, oranye = kurang lengkap, merah = tidak memakai APD,
abu-abu = status belum stabil (belum CONFIRM_FRAMES), biru = APD yang terdeteksi.

Runner hanya menyimpan referensi frame + hasil (murah). Gambar + encode JPEG baru dikerjakan saat ada
yang menonton, dan di-cache per frame supaya banyak penonton cukup satu kali encode."""
import threading
import time
from dataclasses import dataclass

import cv2

from app.services.inference.compliance import KURANG, LENGKAP, TIDAK

MAX_WIDTH = 1280
THUMB_WIDTH = 480         # versi kecil untuk kartu dashboard
JPEG_QUALITY = 75

# warna BGR
_STATUS_COLOR = {LENGKAP: (60, 170, 40), KURANG: (0, 140, 255), TIDAK: (40, 40, 220)}
_PENDING_COLOR = (140, 140, 140)
_APD_COLOR = (200, 120, 0)
_STATUS_TEXT = {LENGKAP: "APD lengkap", KURANG: "Kurang lengkap", TIDAK: "Tanpa APD"}


@dataclass(frozen=True)
class PersonOverlay:
    track_id: int
    box: tuple
    status: str | None              # status yang sudah stabil; None = masih diperiksa
    missing: tuple[str, ...] = ()   # nama APD yang tidak dipakai (untuk label)


@dataclass(frozen=True)
class ItemOverlay:
    name: str
    box: tuple


class LivePreview:
    """Frame beranotasi terakhir.

    Tanpa `raw_source` (video unggahan): yang ditampilkan frame yang diinferensi.
    Dengan `raw_source` (stream CCTV): callable yang mengembalikan StreamWorker (punya `frame_seq` dan
    `get_latest()`); yang ditampilkan frame kamera TERBARU (fps penuh) dengan kotak hasil inferensi
    terakhir, selama hasil itu belum lebih tua dari `max_age` detik. Jadi video tetap mulus walau
    inferensi hanya target_fps kali per detik."""

    def __init__(self, raw_source=None, max_age: float = 1.0):
        self.raw_source = raw_source
        self.max_age = max_age
        self._lock = threading.Lock()          # dipegang singkat oleh runner saat update
        self._encode_lock = threading.Lock()   # satu encode per frame untuk semua penonton
        self._seq = 0
        self._updated = 0.0
        self._frame = None
        self._persons: tuple[PersonOverlay, ...] = ()
        self._items: tuple[ItemOverlay, ...] = ()
        self._cache: dict[int, tuple] = {}     # lebar -> (kunci, JPEG)

    def _worker(self):
        return self.raw_source() if self.raw_source else None

    @property
    def seq(self):
        """Berubah setiap ada frame kamera baru atau hasil inferensi baru."""
        worker = self._worker()
        raw_seq = worker.frame_seq if worker is not None and worker.latest_frame is not None else None
        return (raw_seq, self._seq)

    def update(self, frame, persons, items) -> None:
        """Dipanggil runner tiap selesai satu frame. Frame tidak boleh diubah setelah ini."""
        with self._lock:
            self._frame, self._persons, self._items = frame, tuple(persons), tuple(items)
            self._seq += 1
            self._updated = time.monotonic()

    def jpeg(self, max_width: int = MAX_WIDTH):
        """(kunci, JPEG beranotasi selebar maks. max_width); bytes None kalau belum ada frame."""
        with self._encode_lock:
            with self._lock:
                seq, frame, persons, items, updated = self._seq, self._frame, self._persons, self._items, self._updated
            worker = self._worker()
            raw_seq, raw = (worker.get_latest() if worker is not None else (None, None))
            key = (raw_seq if raw is not None else None, seq)
            cached = self._cache.get(max_width)
            if cached and cached[0] == key:
                return cached
            if raw is not None:
                if time.monotonic() - updated > self.max_age:     # hasil inferensi basi: jangan gambar kotak lama
                    persons, items = (), ()
                frame = raw
            if frame is None:
                return key, None
            self._cache[max_width] = (key, encode_jpeg(annotate(frame, persons, items, max_width)))
            return self._cache[max_width]


def annotate(frame, persons, items, max_width: int = MAX_WIDTH):
    """Salinan frame (diperkecil ke max_width) dengan kotak orang + APD."""
    h, w = frame.shape[:2]
    f = min(1.0, max_width / w) if w else 1.0
    img = cv2.resize(frame, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA) if f < 1 else frame.copy()
    scale = max(0.45, min(img.shape[:2]) / 1000)
    thick = max(1, round(scale * 2))

    for item in items:
        x1, y1, x2, y2 = (int(v * f) for v in item.box)
        cv2.rectangle(img, (x1, y1), (x2, y2), _APD_COLOR, max(1, thick - 1))
        _label(img, item.name, (x1, y1), _APD_COLOR, scale * 0.8, max(1, thick - 1))

    for p in persons:
        color = _STATUS_COLOR.get(p.status, _PENDING_COLOR)
        x1, y1, x2, y2 = (int(v * f) for v in p.box)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick + 1)
        if p.status is None:
            text = f"ID{p.track_id} memeriksa..."
        elif p.status != LENGKAP and p.missing:
            text = f"ID{p.track_id} tanpa {', '.join(p.missing)}"
        else:
            text = f"ID{p.track_id} {_STATUS_TEXT.get(p.status, p.status)}"
        _label(img, text, (x1, y1), color, scale, thick)
    return img


def encode_jpeg(img) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("Gagal encode JPEG")
    return buf.tobytes()


def _label(img, text: str, org: tuple[int, int], color, scale: float, thick: int) -> None:
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x = max(0, min(org[0], img.shape[1] - tw - 6))      # geser ke kiri kalau terpotong tepi kanan
    y = max(org[1], th + base + 4)
    cv2.rectangle(img, (x, y - th - base - 4), (x + tw + 6, y), color, -1)
    cv2.putText(img, text, (x + 3, y - base - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)
