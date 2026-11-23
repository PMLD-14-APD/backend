"""Auto-reconnect kamera CCTV: worker tidak menyerah saat kamera mati, sesi menunggu, live view memberi tanda."""
import threading
import time

import numpy as np
import pytest

from app.services import stream_manager as sm_module
from app.services.inference import session_runner
from app.services.inference.preview import CONNECTING_TEXT, LivePreview
from app.services.stream_worker import CONNECTED, CONNECTING, RECONNECTING, StreamWorker


class FakeCap:
    def __init__(self, frames: int, opened: bool = True):
        self.left, self.opened, self.released = frames, opened, False

    def isOpened(self):
        return self.opened

    def read(self):
        if self.left <= 0:
            return False, None
        self.left -= 1
        time.sleep(0.002)
        return True, np.zeros((36, 64, 3), dtype=np.uint8)

    def release(self):
        self.released = True


class ScriptedOpener:
    """Tiap panggilan mengambil skrip berikutnya: None = kamera mati, int = jumlah frame lalu putus.
    Setelah skrip habis, kamera menyala terus (frame tanpa batas)."""

    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def __call__(self, url, timeout):
        self.calls += 1
        step = self.script.pop(0) if self.script else 10**9
        return FakeCap(0, opened=False) if step is None else FakeCap(step)


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def make_worker(opener, sid="s1"):
    return StreamWorker(sid, "http://cam/video", 5, opener=opener,
                        retry_min_seconds=0.01, retry_max_seconds=0.05)


def test_kamera_mati_di_awal_lalu_menyala_tersambung_sendiri():
    opener = ScriptedOpener([None, None, None])
    w = make_worker(opener)
    assert w.state == CONNECTING and w.offline_seconds() >= 0
    w.start()
    try:
        assert wait_until(lambda: w.connected), "worker harus tersambung setelah kamera menyala"
        assert w.is_alive() and opener.calls >= 4
        assert w.offline_seconds() == 0.0 and w.frame_seq > 0
    finally:
        w.stop()
        w.join(1)
    assert not w.is_alive()


def test_putus_di_tengah_lalu_kembali():
    opener = ScriptedOpener([5, None, None])
    w = make_worker(opener)
    w.start()
    try:
        assert wait_until(lambda: w.frame_seq >= 5)
        assert wait_until(lambda: w.connected and w.frame_seq > 5), "frame harus mengalir lagi setelah putus"
        assert opener.calls >= 4
    finally:
        w.stop()
        w.join(1)


def test_state_reconnecting_selama_offline():
    opener = ScriptedOpener([3] + [None] * 1000)
    w = make_worker(opener)
    w.start()
    try:
        assert wait_until(lambda: w.state == RECONNECTING)
        assert wait_until(lambda: w.offline_seconds() > 0.05)
        assert w.is_alive(), "worker tidak boleh mati walau kamera offline lama"
    finally:
        w.stop()
        w.join(1)
    assert not w.is_alive()


def test_opener_error_tidak_mematikan_worker():
    calls = {"n": 0}

    def opener(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("boom")
        return FakeCap(10**9)

    w = make_worker(opener)
    w.start()
    try:
        assert wait_until(lambda: w.connected)
    finally:
        w.stop()
        w.join(1)


@pytest.fixture
def manager(monkeypatch):
    m = sm_module.StreamManager()
    monkeypatch.setattr(session_runner, "stream_manager", m)
    yield m
    m.stop_all()


def test_iter_stream_frames_menunggu_kamera_lalu_lanjut(manager):
    opener = ScriptedOpener([None] * 5)
    w = make_worker(opener, "s2")
    manager.workers["s2"] = w
    w.start()
    stop = threading.Event()
    got = []

    def consume():
        for n, _ts, _f in session_runner.iter_stream_frames("s2", stop, 50, giveup_seconds=0):
            got.append(n)
            if n >= 3:
                stop.set()

    t = threading.Thread(target=consume)
    t.start()
    t.join(3)
    assert not t.is_alive() and got[:3] == [1, 2, 3]


def test_iter_stream_frames_menyerah_setelah_batas(manager):
    w = make_worker(ScriptedOpener([None] * 10**6), "s3")
    manager.workers["s3"] = w
    w.start()
    with pytest.raises(RuntimeError, match="offline lebih dari"):
        for _ in session_runner.iter_stream_frames("s3", threading.Event(), 5, giveup_seconds=0.2):
            pass


def test_state_of_dan_status(manager):
    w = make_worker(ScriptedOpener([None] * 10**6), "s4")
    manager.workers["s4"] = w
    st = manager.state_of("s4")
    assert st["state"] == CONNECTING and st["connected"] is False
    assert manager.state_of("tidak-ada") is None
    assert manager.status()["s4"]["running"] is True


class OfflineWorker:
    connected = False
    frame_seq = 0
    latest_frame = None

    def get_latest(self):
        return 0, None


class OnlineWorker:
    def __init__(self):
        self.connected, self.frame_seq = True, 1
        self.latest_frame = np.zeros((72, 128, 3), dtype=np.uint8)

    def get_latest(self):
        return self.frame_seq, self.latest_frame.copy()


def test_preview_kamera_belum_pernah_menyala_tetap_ada_gambar():
    p = LivePreview(raw_source=lambda: OfflineWorker())
    key, data = p.jpeg(320)
    assert data is not None and data[:2] == b"\xff\xd8", "harus ada layar 'menghubungkan' walau belum ada frame"
    assert key[-1] is True
    assert CONNECTING_TEXT


def test_preview_berubah_saat_offline_dan_online_lagi():
    worker = OnlineWorker()
    p = LivePreview(raw_source=lambda: worker)
    seq_on = p.seq
    key_on, jpg_on = p.jpeg(128)
    worker.connected = False
    assert p.seq != seq_on, "perubahan online->offline harus memicu kirim frame baru"
    key_off, jpg_off = p.jpeg(128)
    assert key_off != key_on and jpg_off != jpg_on
    worker.connected = True
    assert p.jpeg(128)[0] == key_on
