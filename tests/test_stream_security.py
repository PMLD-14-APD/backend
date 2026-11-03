import time

import pytest

from app.services.stream_probe import probe_stream
from app.services.stream_url import mask_stream_url, validate_stream_url


# ---------- validate_stream_url ----------
@pytest.mark.parametrize("url", [
    "rtsp://admin:rahasia@192.168.1.10:554/stream",
    "rtsps://cam.example.com/live",
    "http://10.0.0.5:8080/video",
    "https://cam.example.com/hls/index.m3u8?token=abc",
    "RTSP://host/x",
])
def test_url_valid(url):
    assert validate_stream_url(url).lower().startswith(url.split("://")[0].lower() + "://")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "/etc/passwd",
    "C:\\videos\\a.mp4",
    "ftp://host/x",
    "0",
    "rtsp://",
    "rtsp://:554/x",
    "rtsp://admin@/x",
    "rtsp://host/has space",
    "rtsp://admin:pa/ss@host/x",      # '/' tak di-encode di password
    "rtsp://host/x\nGET /",
    "   ",
])
def test_url_ditolak(url):
    with pytest.raises(ValueError):
        validate_stream_url(url)


def test_url_encoded_password_diterima():
    assert validate_stream_url("rtsp://admin:pa%40ss@host/x") == "rtsp://admin:pa%40ss@host/x"


def test_at_di_password_tetap_aman_disamarkan():
    # '@' terakhir dianggap pemisah host, jadi seluruh password tertutup
    url = "rtsp://admin:pa@ss@host/x"
    assert validate_stream_url(url) == url
    assert mask_stream_url(url) == "rtsp://admin:***@host/x"


# ---------- mask_stream_url ----------
def test_mask_password():
    assert mask_stream_url("rtsp://admin:rahasia@192.168.1.10:554/stream") == "rtsp://admin:***@192.168.1.10:554/stream"


def test_mask_tanpa_password_tidak_berubah():
    assert mask_stream_url("rtsp://192.168.1.10:554/stream") == "rtsp://192.168.1.10:554/stream"
    assert mask_stream_url("rtsp://admin@192.168.1.10/stream") == "rtsp://admin@192.168.1.10/stream"


def test_mask_query_rahasia():
    assert mask_stream_url("http://h/v?token=abc&fps=5") == "http://h/v?token=***&fps=5"
    assert mask_stream_url("rtsp://u:p@h/s?password=zzz") == "rtsp://u:***@h/s?password=***"


def test_mask_none_dan_non_url():
    assert mask_stream_url(None) is None
    assert mask_stream_url("0") == "0"


# ---------- probe_stream (opener palsu, tanpa jaringan) ----------
class FakeCap:
    def __init__(self, opened=True, frame_ok=True, delay=0.0):
        self.opened, self.frame_ok, self.delay, self.released = opened, frame_ok, delay, False

    def isOpened(self):
        time.sleep(self.delay)
        return self.opened

    def read(self):
        return (self.frame_ok, object() if self.frame_ok else None)

    def release(self):
        self.released = True


def test_probe_berhasil():
    cap = FakeCap()
    assert probe_stream("rtsp://x", 2, opener=lambda u, t: cap) == (True, None)
    assert cap.released


def test_probe_tidak_bisa_dibuka():
    ok, reason = probe_stream("rtsp://x", 2, opener=lambda u, t: FakeCap(opened=False))
    assert ok is False and "tidak bisa dibuka" in reason


def test_probe_tanpa_frame():
    ok, reason = probe_stream("rtsp://x", 2, opener=lambda u, t: FakeCap(frame_ok=False))
    assert ok is False and "frame" in reason


def test_probe_timeout_keras():
    start = time.time()
    ok, reason = probe_stream("rtsp://x", 0.3, opener=lambda u, t: FakeCap(delay=2))
    assert ok is False and "tidak merespons" in reason and time.time() - start < 1.5


def test_probe_exception_tidak_membocorkan_url():
    def boom(u, t):
        raise RuntimeError(f"gagal {u}")
    ok, reason = probe_stream("rtsp://admin:rahasia@h/x", 2, opener=boom)
    assert ok is False and "rahasia" not in reason