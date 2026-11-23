import threading
import time

from app.services.stream_url import mask_stream_url

CONNECTING = "connecting"        # belum pernah dapat frame sejak worker mulai
CONNECTED = "connected"          # frame mengalir
RECONNECTING = "reconnecting"    # kamera offline / putus, sedang dicoba lagi


def open_capture(url: str, timeout: float):
    """VideoCapture dengan batas waktu buka/baca, supaya kamera mati tidak membuat thread menggantung."""
    import cv2

    ms = int(timeout * 1000)
    try:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, ms,
        ])
    except TypeError:    # OpenCV lama tanpa parameter timeout
        cap = cv2.VideoCapture(url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


class StreamWorker(threading.Thread):
    """Satu thread per sesi analisis CCTV. Nyimpen frame TERBARU aja (bukan antrean),
    biar nggak ada lag menumpuk kalau processing lebih lambat dari stream.
    target_fps dipakai pembaca (inferensi), worker sendiri membaca stream dengan fps penuh.

    Worker TIDAK pernah menyerah sendiri: kalau kamera belum menyala atau putus, ia mencoba lagi
    dengan jeda bertambah (retry_min_seconds, x2, ... sampai retry_max_seconds) sampai di-stop.
    Keputusan menyerah ada di pembaca (lihat STREAM_OFFLINE_GIVEUP_MINUTES)."""

    def __init__(self, session_id: str, stream_url: str, target_fps: int = 5, on_frame=None, *,
                 opener=None, open_timeout: float = 8.0,
                 retry_min_seconds: float = 2.0, retry_max_seconds: float = 15.0):
        super().__init__(daemon=True)
        self.session_id = session_id
        self.stream_url = stream_url
        self.target_fps = target_fps
        self.interval = 1.0 / max(target_fps, 1)

        # callback opsional: dipanggil tiap ada frame baru, misal buat lempar ke inference
        self.on_frame = on_frame
        self.opener = opener or open_capture
        self.open_timeout = open_timeout
        self.retry_min = retry_min_seconds
        self.retry_max = max(retry_max_seconds, retry_min_seconds)

        self.latest_frame = None
        self.frame_seq = 0
        self.lock = threading.Lock()
        self.running = True
        self._stop_event = threading.Event()

        self.state = CONNECTING
        self.offline_since = time.monotonic()   # None saat frame mengalir
        self.last_frame_at = None                # time.monotonic() frame terakhir
        self.reconnect_attempts = 0              # percobaan gagal berturut-turut

    # ------------------------------------------------------------------ status
    @property
    def connected(self) -> bool:
        return self.state == CONNECTED

    def offline_seconds(self) -> float:
        since = self.offline_since
        return 0.0 if since is None else time.monotonic() - since

    def _set_offline(self):
        if self.offline_since is None:
            self.offline_since = time.monotonic()
        if self.state == CONNECTED:
            self.state = RECONNECTING

    # ------------------------------------------------------------------ loop
    def _wait_retry(self):
        delay = min(self.retry_max, self.retry_min * (2 ** min(self.reconnect_attempts, 10)))
        self.reconnect_attempts += 1
        self._stop_event.wait(delay)

    def _open(self):
        try:
            cap = self.opener(self.stream_url, self.open_timeout)
        except Exception as exc:  # noqa: BLE001 - opener rusak tidak boleh mematikan worker
            print(f"[stream:{self.session_id}] gagal membuka stream ({type(exc).__name__})")
            return None
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            return None
        return cap

    def run(self):
        url = mask_stream_url(self.stream_url)
        cap = None
        while self.running:
            if cap is None:
                cap = self._open()
                if cap is None:
                    self._set_offline()
                    if self.reconnect_attempts == 0 or self.reconnect_attempts % 10 == 0:
                        print(f"[stream:{self.session_id}] Kamera belum bisa dihubungi ({url}), mencoba lagi...")
                    self._wait_retry()
                    continue

            ret, frame = cap.read()
            if not ret or frame is None:
                if self.state == CONNECTED:
                    print(f"[stream:{self.session_id}] Stream putus, menyambung ulang...")
                cap.release()
                cap = None
                self._set_offline()
                self._wait_retry()
                continue

            if self.state != CONNECTED:
                print(f"[stream:{self.session_id}] Terhubung: {url}")
            # Simpan SETIAP frame (tampilan live jadi mulus); laju inferensi dibatasi oleh pembacanya
            # (iter_stream_frames, sesuai target_fps), bukan di sini.
            with self.lock:
                self.latest_frame = frame
                self.frame_seq += 1
            self.state = CONNECTED
            self.offline_since = None
            self.last_frame_at = time.monotonic()
            self.reconnect_attempts = 0

            if self.on_frame:
                self.on_frame(self.session_id, frame)

        if cap is not None:
            cap.release()
        self.state = CONNECTING if self.last_frame_at is None else RECONNECTING

    def get_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_latest(self):
        """Return (seq, frame) terbaru; frame None kalau belum ada."""
        with self.lock:
            return self.frame_seq, (self.latest_frame.copy() if self.latest_frame is not None else None)

    def stop(self):
        self.running = False
        self._stop_event.set()
