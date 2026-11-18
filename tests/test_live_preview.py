"""Tes tayangan langsung beranotasi (/analysis-sessions/{id}/live.mjpg & preview.jpg) + LivePreview."""
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.analysis import AnalysisSession
from app.models.environment import Environment
from app.models.user import User
from app.models.video_source import VideoSource
from app.services.inference.compliance import KURANG, LENGKAP, TIDAK
from app.services.inference.manager import inference_manager
from app.services.inference.preview import MAX_WIDTH, ItemOverlay, LivePreview, PersonOverlay, annotate

JPEG_MAGIC = b"\xff\xd8"


def frame(w=640, h=360):
    return np.full((h, w, 3), 90, dtype=np.uint8)


# ---------------------------------------------------------------------------
# LivePreview / annotate (murni)
# ---------------------------------------------------------------------------
def test_preview_kosong_sebelum_ada_frame():
    assert LivePreview().jpeg()[1] is None


def test_preview_encode_sekali_per_frame():
    p = LivePreview()
    p.update(frame(), [PersonOverlay(1, (10, 10, 100, 200), TIDAK, ("Helm", "Rompi"))], [])
    key, first = p.jpeg()
    assert key == p.seq and first.startswith(JPEG_MAGIC)
    assert p.jpeg()[1] is first                      # cache: tidak encode ulang untuk frame yang sama
    p.update(frame(), [], [])
    key2, second = p.jpeg()
    assert key2 != key and key2 == p.seq and second is not first


class FakeWorker:
    def __init__(self):
        self.frame_seq, self.latest_frame = 0, None

    def push(self, value):
        self.frame_seq += 1
        self.latest_frame = np.full((360, 640, 3), value, dtype=np.uint8)

    def get_latest(self):
        return self.frame_seq, (None if self.latest_frame is None else self.latest_frame.copy())


def _decoded(data):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def test_stream_pakai_frame_kamera_terbaru_dengan_kotak_terakhir(monkeypatch):
    worker = FakeWorker()
    p = LivePreview(raw_source=lambda: worker, max_age=1.0)
    p.update(frame(), [PersonOverlay(1, (100, 50, 300, 300), TIDAK)], [])   # hasil inferensi frame lama
    worker.push(200)                                                        # frame kamera yang lebih baru
    key, data = p.jpeg()
    assert key == p.seq == (1, 1)
    img = _decoded(data)
    assert abs(int(img[200, 500, 0]) - 200) < 10          # latar = frame kamera terbaru, bukan frame inferensi (90)
    assert img[200, 100, 2] > 150 and img[200, 100, 0] < 120   # garis kotak merah tetap digambar

    worker.push(200)                                       # frame baru lagi -> kunci berubah, encode ulang
    assert p.seq == (2, 1) and p.jpeg()[0] == (2, 1)

    import app.services.inference.preview as preview_mod   # hasil inferensi basi -> kotak tidak digambar
    now = preview_mod.time.monotonic()
    monkeypatch.setattr(preview_mod.time, "monotonic", lambda: now + 5)
    worker.push(200)
    img = _decoded(p.jpeg()[1])
    assert abs(int(img[200, 100, 2]) - 200) < 10


def test_stream_belum_ada_frame_kamera_pakai_frame_inferensi():
    worker = FakeWorker()
    p = LivePreview(raw_source=lambda: worker)
    assert p.seq == (None, 0) and p.jpeg()[1] is None
    p.update(frame(), [], [])
    key, data = p.jpeg()
    assert key == p.seq == (None, 1) and data.startswith(JPEG_MAGIC)


def test_annotate_perkecil_frame_besar_dan_tahan_kotak_di_tepi():
    big = frame(3840, 2160)
    persons = [
        PersonOverlay(1, (3700, 0, 3840, 400), LENGKAP),            # menempel tepi kanan/atas
        PersonOverlay(2, (0, 1800, 300, 2160), KURANG, ("Rompi",)),
        PersonOverlay(3, (1000, 500, 1200, 900), None),              # belum stabil
    ]
    out = annotate(big, persons, [ItemOverlay("Helm", (3710, 0, 3800, 60))])
    assert out.shape[1] == MAX_WIDTH and out.shape[0] == 720
    assert not np.shares_memory(out, big)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class FakeRunner:
    """Pengganti SessionRunner: hidup selama `ticks` kali dicek is_alive()."""

    def __init__(self, ticks=10**9):
        self.preview = LivePreview()
        self.preview.update(frame(), [PersonOverlay(7, (10, 10, 120, 300), TIDAK, ("Helm",))], [])
        self.ticks = ticks

    def is_alive(self):
        self.ticks -= 1
        return self.ticks >= 0


@pytest.fixture()
def env(monkeypatch):
    security._revoked.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override
    db = Session()
    monkeypatch.setattr(inference_manager, "runners", {})

    class Ctx:
        client = TestClient(app)

        def user(self, username, role="user"):
            u = User(name=username.title(), username=username, password_hash=hash_password("rahasia123"),
                     role=role, status="active")
            db.add(u); db.commit(); db.refresh(u)
            return u

        def token(self, user):
            return create_access_token({"sub": str(user.id)})

        def h(self, user):
            return {"Authorization": f"Bearer {self.token(user)}"}

        def session(self, owner, status="processing"):
            e = db.query(Environment).first() or Environment(name="Konstruksi")
            db.add(e); db.commit()
            s = VideoSource(user_id=owner.id, environment_id=e.id, name="cam", source_type="cctv_stream",
                            stream_url="rtsp://h/x", target_fps=5, status="active")
            db.add(s); db.commit(); db.refresh(s)
            a = AnalysisSession(source_id=s.id, model_id=uuid.uuid4(), status=status)
            db.add(a); db.commit(); db.refresh(a)
            return a

    yield Ctx()
    app.dependency_overrides.clear()
    db.close()


def test_wajib_login(env):
    sess = env.session(env.user("owner"))
    inference_manager.runners[str(sess.id)] = FakeRunner()
    for path in ("preview.jpg", "live.mjpg"):
        assert env.client.get(f"/analysis-sessions/{sess.id}/{path}").status_code == 401
        assert env.client.get(f"/analysis-sessions/{sess.id}/{path}?token=ngawur").status_code == 401


def test_hanya_pemilik_atau_admin(env):
    owner, other, admin = env.user("owner"), env.user("other"), env.user("boss", role="admin")
    sess = env.session(owner)
    inference_manager.runners[str(sess.id)] = FakeRunner()
    url = f"/analysis-sessions/{sess.id}/preview.jpg"
    assert env.client.get(url, headers=env.h(other)).status_code == 404
    for u in (owner, admin):
        r = env.client.get(url, headers=env.h(u))
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert r.content.startswith(JPEG_MAGIC) and "no-store" in r.headers["cache-control"]
    # tag <img> tanpa header boleh lewat ?token= (sama seperti foto bukti)
    assert env.client.get(f"{url}?token={env.token(owner)}").status_code == 200


def test_404_kalau_sesi_tidak_berjalan(env):
    owner = env.user("owner")
    done = env.session(owner, status="done")
    inference_manager.runners[str(done.id)] = FakeRunner()          # runner sisa, tapi sesi sudah selesai
    no_runner = env.session(owner)                                    # processing tapi runner tidak ada
    dead = env.session(owner)
    inference_manager.runners[str(dead.id)] = FakeRunner(ticks=0)
    for sess in (done, no_runner, dead):
        for path in ("preview.jpg", "live.mjpg"):
            assert env.client.get(f"/analysis-sessions/{sess.id}/{path}", headers=env.h(owner)).status_code == 404
    assert env.client.get(f"/analysis-sessions/{uuid.uuid4()}/preview.jpg", headers=env.h(owner)).status_code == 404


def test_mjpeg_mengirim_frame_dan_berhenti_saat_runner_selesai(env):
    owner = env.user("owner")
    sess = env.session(owner)
    inference_manager.runners[str(sess.id)] = FakeRunner(ticks=6)   # 1x dicek endpoint, sisanya oleh stream
    with env.client.stream("GET", f"/analysis-sessions/{sess.id}/live.mjpg", headers=env.h(owner)) as r:
        assert r.status_code == 200
        assert r.headers["content-type"] == "multipart/x-mixed-replace; boundary=frame"
        body = b"".join(r.iter_bytes())
    assert body.startswith(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ")
    head, _, rest = body.partition(b"\r\n\r\n")
    length = int(head.rsplit(b": ", 1)[1])
    assert rest[:length].startswith(JPEG_MAGIC) and rest[length:length + 2] == b"\r\n"


def test_ukuran_thumb_lebih_kecil_dan_di_cache_terpisah():
    p = LivePreview()
    p.update(frame(1280, 720), [PersonOverlay(1, (10, 10, 300, 600), TIDAK, ("Helm",))], [])
    _, full = p.jpeg()
    _, thumb = p.jpeg(480)
    assert _decoded(full).shape[1] == 1280 and _decoded(thumb).shape[1] == 480
    assert p.jpeg()[1] is full and p.jpeg(480)[1] is thumb


def test_api_size_thumb(env):
    owner = env.user("owner")
    sess = env.session(owner)
    inference_manager.runners[str(sess.id)] = FakeRunner()
    r = env.client.get(f"/analysis-sessions/{sess.id}/preview.jpg?size=thumb", headers=env.h(owner))
    assert r.status_code == 200 and _decoded(r.content).shape[1] == 480
    assert env.client.get(f"/analysis-sessions/{sess.id}/preview.jpg?size=raksasa", headers=env.h(owner)).status_code == 422
