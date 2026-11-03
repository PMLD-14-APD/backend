"""Tes /video-sources dan /locations memakai SQLite in-memory (butuh: pip install httpx)."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import video_sources as vs_api
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.analysis import AnalysisSession
from app.models.environment import Environment, Location
from app.models.user import User
from app.models.video_source import VideoSource

URL = "rtsp://admin:rahasia@192.168.1.10:554/stream"


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    db = Session()
    monkeypatch.setattr(settings, "cctv_register_admin_only", False)   # default: ikut ERD
    monkeypatch.setattr(settings, "validate_stream_on_create", True)

    class Ctx:
        client = TestClient(app)

        def user(self, username, role="user"):
            u = User(name=username.title(), username=username, password_hash=hash_password("rahasia123"),
                     role=role, status="active")
            db.add(u); db.commit(); db.refresh(u)
            return u

        def headers(self, user):
            return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}

        def environment(self, name="Konstruksi"):
            e = Environment(name=name); db.add(e); db.commit(); db.refresh(e)
            return e

        def location(self, name):
            l = Location(name=name); db.add(l); db.commit(); db.refresh(l)
            return l

        def source(self, owner, env_, name, location=None, source_type="cctv_stream", url=URL, status="active"):
            s = VideoSource(user_id=owner.id, environment_id=env_.id, location_id=location.id if location else None,
                            name=name, source_type=source_type,
                            stream_url=url if source_type == "cctv_stream" else None,
                            file_path="C:/server/rahasia/video.mp4" if source_type == "video_upload" else None,
                            target_fps=5, status=status)
            db.add(s); db.commit(); db.refresh(s)
            return s

        def session(self, src, status="processing"):
            a = AnalysisSession(source_id=src.id, model_id=uuid.uuid4(), status=status)
            db.add(a); db.commit(); db.refresh(a)
            return a

    ctx = Ctx()
    ctx.db = db
    yield ctx
    app.dependency_overrides.clear()
    db.close()


# ---------- pendaftaran CCTV ----------
def test_user_biasa_boleh_daftar_cctv_secara_default(env, monkeypatch):
    monkeypatch.setattr(vs_api, "probe_stream", lambda url, timeout: (True, None))
    user, e = env.user("operator"), env.environment()
    r = env.client.post("/video-sources/", headers=env.headers(user),
                        json={"name": "Gate", "stream_url": URL, "environment_id": str(e.id)})
    assert r.status_code == 201


def test_flag_admin_only_menolak_user_biasa(env, monkeypatch):
    monkeypatch.setattr(settings, "cctv_register_admin_only", True)
    user, admin, e = env.user("operator"), env.user("admin1", "admin"), env.environment()
    body = {"name": "Gate", "stream_url": URL, "environment_id": str(e.id)}
    assert env.client.post("/video-sources/", headers=env.headers(user), json=body).status_code == 403
    monkeypatch.setattr(vs_api, "probe_stream", lambda url, timeout: (True, None))
    assert env.client.post("/video-sources/", headers=env.headers(admin), json=body).status_code == 201


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "/etc/passwd", "ftp://x/y", "rtsp://"])
def test_url_berbahaya_ditolak_422(env, bad, monkeypatch):
    monkeypatch.setattr(vs_api, "probe_stream", lambda *a, **k: pytest.fail("probe tidak boleh dipanggil"))
    admin, e = env.user("admin1", "admin"), env.environment()
    r = env.client.post("/video-sources/", headers=env.headers(admin),
                        json={"name": "X", "stream_url": bad, "environment_id": str(e.id)})
    assert r.status_code == 422


def test_koneksi_gagal_ditolak_tanpa_membocorkan_password(env, monkeypatch):
    monkeypatch.setattr(vs_api, "probe_stream", lambda url, timeout: (False, "stream tidak bisa dibuka"))
    admin, e = env.user("admin1", "admin"), env.environment()
    r = env.client.post("/video-sources/", headers=env.headers(admin),
                        json={"name": "X", "stream_url": URL, "environment_id": str(e.id)})
    assert r.status_code == 422 and "rahasia" not in r.text
    assert env.db.query(VideoSource).count() == 0


def test_daftar_berhasil_response_disamarkan_db_tetap_asli(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(vs_api, "probe_stream", lambda url, timeout: seen.setdefault("url", url) and (True, None))
    admin, e = env.user("admin1", "admin"), env.environment()
    loc = env.location("Gedung A")
    r = env.client.post("/video-sources/", headers=env.headers(admin),
                        json={"name": "Gate", "stream_url": URL, "environment_id": str(e.id), "location_id": str(loc.id)})
    assert r.status_code == 201
    body = r.json()
    assert body["stream_url"] == "rtsp://admin:***@192.168.1.10:554/stream"
    assert "rahasia" not in r.text and "file_path" not in body
    assert body["location_name"] == "Gedung A" and body["is_live"] is False
    assert seen["url"] == URL                                     # yang diuji = URL asli
    assert env.db.query(VideoSource).one().stream_url == URL      # yang disimpan = URL asli


def test_validasi_koneksi_bisa_dimatikan(env, monkeypatch):
    monkeypatch.setattr(settings, "validate_stream_on_create", False)
    monkeypatch.setattr(vs_api, "probe_stream", lambda *a, **k: pytest.fail("tidak boleh dipanggil"))
    admin, e = env.user("admin1", "admin"), env.environment()
    r = env.client.post("/video-sources/", headers=env.headers(admin),
                        json={"name": "X", "stream_url": URL, "environment_id": str(e.id)})
    assert r.status_code == 201


# ---------- file_path tersembunyi ----------
def test_file_path_tidak_bocor(env):
    admin, e = env.user("admin1", "admin"), env.environment()
    s = env.source(admin, e, "Rekaman 1", source_type="video_upload", status="uploaded")
    one = env.client.get(f"/video-sources/{s.id}", headers=env.headers(admin))
    page = env.client.get("/video-sources/", headers=env.headers(admin))
    assert "file_path" not in one.json() and "rahasia" not in one.text and "rahasia" not in page.text


# ---------- daftar kamera ----------
def _names(resp):
    return sorted(i["name"] for i in resp.json()["items"])


def test_list_search_nama_kamera_dan_lokasi(env):
    admin, e = env.user("admin1", "admin"), env.environment()
    a, b = env.location("Gedung Auditorium"), env.location("Gudang Bahan Baku")
    env.source(admin, e, "Gate Masuk", a)
    env.source(admin, e, "CCTV Lorong", a)
    env.source(admin, e, "Gate Belakang", b)
    h = env.headers(admin)
    assert _names(env.client.get("/video-sources/?search=gate", headers=h)) == ["Gate Belakang", "Gate Masuk"]
    assert _names(env.client.get("/video-sources/?search=auditorium", headers=h)) == ["CCTV Lorong", "Gate Masuk"]
    assert env.client.get("/video-sources/?search=%25", headers=h).json()["total"] == 0


def test_list_filter_lokasi_tipe_status_dan_location_name(env):
    admin, e = env.user("admin1", "admin"), env.environment()
    a, b = env.location("A"), env.location("B")
    env.source(admin, e, "c1", a, status="active")
    env.source(admin, e, "c2", b, status="inactive")
    env.source(admin, e, "v1", a, source_type="video_upload", status="uploaded")
    h = env.headers(admin)
    assert _names(env.client.get(f"/video-sources/?location_id={a.id}", headers=h)) == ["c1", "v1"]
    assert _names(env.client.get("/video-sources/?source_type=video_upload", headers=h)) == ["v1"]
    assert _names(env.client.get("/video-sources/?status=inactive", headers=h)) == ["c2"]
    items = env.client.get(f"/video-sources/?location_id={b.id}", headers=h).json()["items"]
    assert items[0]["location_name"] == "B"


def test_list_status_live(env):
    admin, e = env.user("admin1", "admin"), env.environment()
    on, off, done, up = (env.source(admin, e, "on"), env.source(admin, e, "off"), env.source(admin, e, "done"),
                         env.source(admin, e, "upl", source_type="video_upload", status="uploaded"))
    sess = env.session(on, "processing")
    env.session(done, "done")
    env.session(up, "processing")     # upload sedang diproses: bukan "live"
    h = env.headers(admin)
    page = env.client.get("/video-sources/", headers=h).json()["items"]
    by = {i["name"]: i for i in page}
    assert by["on"]["is_live"] is True and by["on"]["active_session_id"] == str(sess.id)
    assert by["off"]["is_live"] is False and by["off"]["active_session_id"] is None
    assert by["done"]["is_live"] is False
    assert by["upl"]["is_live"] is False and by["upl"]["active_session_id"] is not None
    assert _names(env.client.get("/video-sources/?live=true", headers=h)) == ["on"]
    assert _names(env.client.get("/video-sources/?live=false", headers=h)) == ["done", "off", "upl"]
    assert env.client.get(f"/video-sources/{on.id}", headers=h).json()["is_live"] is True


def test_list_paginasi_dan_scoping(env):
    admin, user, e = env.user("admin1", "admin"), env.user("operator"), env.environment()
    for i in range(5):
        env.source(admin, e, f"adm{i}")
    env.source(user, e, "milik-user")
    r = env.client.get("/video-sources/?limit=2&offset=0", headers=env.headers(admin)).json()
    assert r["total"] == 6 and len(r["items"]) == 2
    assert _names(env.client.get("/video-sources/", headers=env.headers(user))) == ["milik-user"]


# ---------- lokasi ----------
def test_lokasi_camera_count_dan_search(env):
    admin, e = env.user("admin1", "admin"), env.environment()
    a, b, c = env.location("Gedung A"), env.location("Gudang B"), env.location("Kosong C")
    env.source(admin, e, "Gate Masuk", a)
    env.source(admin, e, "Lorong", a)
    env.source(admin, e, "Rekaman", a, source_type="video_upload", status="uploaded")
    env.source(admin, e, "Gate Gudang", b)
    h = env.headers(admin)
    rows = {l["name"]: l for l in env.client.get("/locations/", headers=h).json()}
    assert rows["Gedung A"]["camera_count"] == 3 and rows["Gudang B"]["camera_count"] == 1
    assert rows["Kosong C"]["camera_count"] == 0

    names = lambda q: [l["name"] for l in env.client.get(f"/locations/?search={q}", headers=h).json()]
    assert names("gudang") == ["Gudang B"]            # cocok nama lokasi
    assert names("lorong") == ["Gedung A"]            # cocok nama kamera di lokasi itu
    assert sorted(names("gate")) == ["Gedung A", "Gudang B"]
    assert names("%25") == []
    assert env.client.get(f"/locations/{a.id}", headers=h).json()["camera_count"] == 3


def test_lokasi_create_update_camera_count(env):
    admin, e = env.user("admin1", "admin"), env.environment()
    h = env.headers(admin)
    created = env.client.post("/locations/", headers=h, json={"name": "Baru"}).json()
    assert created["camera_count"] == 0
    env.source(admin, e, "c1", env.db.get(Location, uuid.UUID(created["id"])))
    upd = env.client.patch(f"/locations/{created['id']}", headers=h, json={"address": "Jl. X"}).json()
    assert upd["camera_count"] == 1 and upd["address"] == "Jl. X"