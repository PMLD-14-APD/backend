"""Uji koneksi stream CCTV sebelum disimpan (SRS 3.1: validasi data dan koneksi sumber)."""
import threading
from typing import Callable, Optional


def _default_opener(url: str, timeout: float):
    import cv2

    ms = int(timeout * 1000)
    try:
        return cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, ms,
        ])
    except TypeError:   # OpenCV lama tanpa parameter timeout; tetap dijaga oleh batas waktu thread
        return cv2.VideoCapture(url)


def probe_stream(url: str, timeout: float = 8.0,
                 opener: Optional[Callable] = None) -> tuple[bool, Optional[str]]:
    """Return (berhasil, alasan_gagal). Stream dianggap sehat kalau bisa dibuka DAN mengirim 1 frame.

    Berjalan di thread terpisah dengan batas waktu keras, karena VideoCapture bisa menggantung lama
    pada host yang tidak merespons. Pesan alasan tidak pernah memuat URL (bisa berisi password)."""
    opener = opener or _default_opener
    result: dict = {}

    def work():
        cap = None
        try:
            cap = opener(url, timeout)
            if not cap.isOpened():
                result["error"] = "stream tidak bisa dibuka (periksa URL, kredensial, dan jaringan)"
                return
            ok, frame = cap.read()
            if not ok or frame is None:
                result["error"] = "stream terbuka tetapi tidak mengirim frame"
                return
            result["ok"] = True
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"gagal menguji stream ({type(exc).__name__})"
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return False, f"stream tidak merespons dalam {timeout:g} detik"
    if result.get("ok"):
        return True, None
    return False, result.get("error", "stream tidak bisa dibuka")