"""Tes foto bukti ber-login (7), retensi/kuota storage (8), dan sesi 30 menit (9).
Memakai SQLite in-memory + folder sementara (butuh: pip install httpx)."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password, session_age_exceeded
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.analysis import AnalysisSession, ComplianceStat, DetectionLog
from app.models.environment import Environment
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.dashboard import RecentViolation
from app.schemas.history import ViolationHistoryItem
from app.services import retention
from app.storage import local
from app.storage.snapshots import snapshot_api_url, snapshot_file

DAY = timedelta(days=1)


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(type_, compiler, **kw):
    """SQLite hanya auto-increment untuk INTEGER PRIMARY KEY; di PostgreSQL tetap BIGINT."""
    return "INTEGER"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "snapshot_dir", str(tmp_path / "snap"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "up"))
    (tmp_path / "snap").mkdir()
    (tmp_path / "up").mkdir()
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

    class Ctx:
        client = TestClient(app)
        root = tmp_path

        def user(self, username, role="user"):
            u = User(name=username.title(), username=username, password_hash=hash_password("rahasia123"),
                     role=role, status="active")
            db.add(u); db.commit(); db.refresh(u)
            return u

        def h(self, user):
            return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}

        def source(self, owner, source_type="cctv_stream", file_path=None, file_size=None, expires_at=None):
            e = db.query(Environment).first() or Environment(name="Konstruksi")
            db.add(e); db.commit()
            s = VideoSource(user_id=owner.id, environment_id=e.id, name="src", source_type=source_type,
                            stream_url="rtsp://h/x" if source_type == "cctv_stream" else None,
                            file_path=file_path, file_size=file_size, target_fps=5,
                            status="active" if source_type == "cctv_stream" else "uploaded", expires_at=expires_at)
            db.add(s); db.commit(); db.refresh(s)
            return s

        def session(self, src, status="processing", finished_at=None, created_at=None):
            a = AnalysisSession(source_id=src.id, model_id=uuid.uuid4(), status=status, finished_at=finished_at,
                                created_at=created_at or datetime.now(timezone.utc))
            db.add(a); db.commit(); db.refresh(a)
            return a

        def log(self, sess, image=True, age_days=0, content=b"\xff\xd8jpeg"):
            url = None
            if image:
                name = f"{uuid.uuid4().hex}.jpg"
                folder = self.root / "snap" / str(sess.id)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(content)
                url = f"/snapshots/{sess.id}/{name}"
            l = DetectionLog(session_id=sess.id, compliance_status="tidak_digunakan", violation_type="NO_HELMET",
                             confidence=0.9, frame_number=1, video_timestamp=1.0, bbox={}, image_url=url,
                             detected_at=datetime.now(timezone.utc) - age_days * DAY)
            db.add(l); db.commit(); db.refresh(l)
            return l

    ctx = Ctx()
    ctx.db = db
    yield ctx
    app.dependency_overrides.clear()
    db.close()


# =====================================================================
# 7. Foto bukti dengan login
# =====================================================================
def test_foto_wajib_login(env):
    owner = env.user("owner")
    log = env.log(env.session(env.source(owner)))
    assert env.client.get(f"/detection-logs/{log.id}/image").status_code == 401
    assert env.client.get(f"/detection-logs/{log.id}/image?token=ngawur").status_code == 401


def test_foto_pemilik_via_header_dan_query_token(env):
    owner = env.user("owner")
    log = env.log(env.session(env.source(owner)), content=b"\xff\xd8ISI-FOTO")
    r = env.client.get(f"/detection-logs/{log.id}/image", headers=env.h(owner))
    assert r.status_code == 200 and r.content == b"\xff\xd8ISI-FOTO" and r.headers["content-type"] == "image/jpeg"
    token = create_access_token({"sub": str(owner.id)})
    assert env.client.get(f"/detection-logs/{log.id}/image?token={token}").status_code == 200


def test_foto_milik_orang_lain_ditolak_admin_boleh(env):
    owner, other, admin = env.user("owner"), env.user("lain"), env.user("admin1", "admin")
    log = env.log(env.session(env.source(owner)))
    assert env.client.get(f"/detection-logs/{log.id}/image", headers=env.h(other)).status_code == 404
    assert env.client.get(f"/detection-logs/{log.id}/image", headers=env.h(admin)).status_code == 200


def test_token_yang_sudah_logout_tidak_bisa_ambil_foto(env):
    owner = env.user("owner")
    log = env.log(env.session(env.source(owner)))
    h = env.h(owner)
    assert env.client.post("/auth/logout", headers=h).status_code == 204
    assert env.client.get(f"/detection-logs/{log.id}/image", headers=h).status_code == 401


def test_foto_tidak_ada_atau_file_hilang_404(env):
    owner = env.user("owner")
    sess = env.session(env.source(owner))
    no_image = env.log(sess, image=False)
    gone = env.log(sess)
    os.remove(snapshot_file(gone.image_url))
    for l in (no_image, gone):
        assert env.client.get(f"/detection-logs/{l.id}/image", headers=env.h(owner)).status_code == 404


def test_path_traversal_ditolak(env):
    owner = env.user("owner")
    (env.root / "rahasia.txt").write_text("JANGAN BOCOR")
    log = env.log(env.session(env.source(owner)), image=False)
    log.image_url = "/snapshots/../rahasia.txt"
    env.db.commit()
    assert snapshot_file(log.image_url) is None
    assert env.client.get(f"/detection-logs/{log.id}/image", headers=env.h(owner)).status_code == 404


def test_folder_snapshots_tidak_lagi_dilayani_statis(env):
    owner = env.user("owner")
    log = env.log(env.session(env.source(owner)))
    assert env.client.get(log.image_url).status_code == 404


def test_image_url_di_output_memakai_endpoint_ber_auth(env):
    owner = env.user("owner")
    log = env.log(env.session(env.source(owner)))
    out = env.client.get(f"/detection-logs/{log.id}", headers=env.h(owner)).json()
    assert out["image_url"] == f"/detection-logs/{log.id}/image"
    assert "/snapshots/" not in env.client.get("/detection-logs/", headers=env.h(owner)).text
    assert snapshot_api_url(5, None) is None


def test_schema_history_dan_dashboard_menyamarkan_path(env):
    common = dict(id=7, session_id=uuid.uuid4(), track_id=1, compliance_status="tidak_digunakan",
                  violation_type="NO_HELMET", confidence=0.9, detected_at=datetime.now(timezone.utc))
    rv = RecentViolation(source_id=uuid.uuid4(), source_name="s", location_name=None,
                         image_url="/snapshots/a/b.jpg", **common)
    assert rv.image_url == "/detection-logs/7/image"
    vh = ViolationHistoryItem(source_id=uuid.uuid4(), source_name="s", source_type="cctv_stream", location_id=None,
                              location_name=None, violation_label="x", frame_number=1, video_timestamp=1.0, bbox={},
                              image_url=None, items=[], **common)
    assert vh.image_url is None


def test_hapus_sumber_menghapus_foto_buktinya(env):
    owner = env.user("owner")
    sess = env.session(env.source(owner), status="done")
    env.log(sess)
    folder = env.root / "snap" / str(sess.id)
    assert folder.exists()
    src_id = sess.source_id
    assert env.client.delete(f"/video-sources/{src_id}", headers=env.h(owner)).status_code == 200
    assert not folder.exists()


# =====================================================================
# 8. Retensi dan kuota storage
# =====================================================================
def test_purge_old_snapshots_hanya_file_lama(env):
    owner = env.user("owner")
    sess = env.session(env.source(owner))
    old, new = env.log(sess, age_days=100), env.log(sess, age_days=1)
    old_file, new_file = snapshot_file(old.image_url), snapshot_file(new.image_url)
    assert retention.purge_old_snapshots(env.db, 90) == 1
    env.db.refresh(old); env.db.refresh(new)
    assert not old_file.exists() and old.image_url is None       # log tetap ada, fotonya hilang
    assert new_file.exists() and new.image_url is not None
    assert retention.purge_old_snapshots(env.db, 0) == 0         # 0 = nonaktif


def test_purge_old_history(env):
    owner = env.user("owner")
    src = env.source(owner)
    old_done = env.session(src, "done", finished_at=datetime.now(timezone.utc) - 400 * DAY)
    old_running = env.session(src, "processing", created_at=datetime.now(timezone.utc) - 400 * DAY)
    recent_done = env.session(src, "done", finished_at=datetime.now(timezone.utc) - 5 * DAY)
    old_log, keep_log = env.log(old_running, age_days=400), env.log(recent_done, age_days=1)
    env.log(old_done, age_days=400)
    env.db.add(ComplianceStat(session_id=old_running.id, bucket_start=datetime.now(timezone.utc) - 400 * DAY))
    env.db.add(ComplianceStat(session_id=recent_done.id, bucket_start=datetime.now(timezone.utc) - 1 * DAY))
    env.db.commit()
    old_done_id, old_running_id, recent_done_id, keep_log_id = old_done.id, old_running.id, recent_done.id, keep_log.id
    old_folder = env.root / "snap" / str(old_done_id)

    res = retention.purge_old_history(env.db, 365)
    assert res == {"logs": 2, "stats": 1, "sessions": 1}
    ids = {s.id for s in env.db.query(AnalysisSession)}
    assert old_done_id not in ids and old_running_id in ids and recent_done_id in ids   # sesi berjalan aman
    assert env.db.query(DetectionLog).count() == 1 and env.db.query(DetectionLog).one().id == keep_log_id
    assert not old_folder.exists()
    assert retention.purge_old_history(env.db, 0) == {"logs": 0, "stats": 0, "sessions": 0}


def test_sweep_orphans(env):
    owner = env.user("owner")
    sess = env.session(env.source(owner))
    env.log(sess)                                           # folder milik sesi hidup
    orphan_dir = env.root / "snap" / str(uuid.uuid4())      # sesinya tidak ada
    orphan_dir.mkdir(); (orphan_dir / "a.jpg").write_bytes(b"x")
    (env.root / "snap" / "bukan-uuid").mkdir()              # nama asing: jangan disentuh

    kept = env.root / "up" / "dipakai.mp4"; kept.write_bytes(b"x")
    env.source(owner, "video_upload", file_path=str(kept), file_size=1)
    old_orphan = env.root / "up" / "yatim-lama.mp4"; old_orphan.write_bytes(b"x")
    young_orphan = env.root / "up" / "yatim-baru.mp4"; young_orphan.write_bytes(b"x")
    past = time.time() - 7200
    os.utime(old_orphan, (past, past)); os.utime(kept, (past, past))

    res = retention.sweep_orphans(env.db)
    assert res == {"orphan_snapshot_dirs": 1, "orphan_upload_files": 1}
    assert not orphan_dir.exists() and (env.root / "snap" / str(sess.id)).exists()
    assert (env.root / "snap" / "bukan-uuid").exists()
    assert kept.exists() and young_orphan.exists() and not old_orphan.exists()


def test_purge_expired_uploads_hapus_file_dan_foto(env):
    owner = env.user("owner")
    f = env.root / "up" / "lama.mp4"; f.write_bytes(b"x")
    src = env.source(owner, "video_upload", file_path=str(f), file_size=1,
                     expires_at=datetime.now(timezone.utc) - DAY)
    sess = env.session(src, "done")
    env.log(sess)
    folder = env.root / "snap" / str(sess.id)
    assert local.purge_expired_uploads(env.db) == 1
    assert not f.exists() and not folder.exists()


def test_kuota_penuh_menolak_upload(env, monkeypatch):
    monkeypatch.setattr(settings, "storage_quota_mb", 1)
    owner = env.user("owner")
    e = Environment(name="K"); env.db.add(e); env.db.commit()
    form = {"name": "v", "environment_id": str(e.id)}

    # sudah penuh sebelum upload
    env.source(owner, "video_upload", file_path="x", file_size=2 * 1024 * 1024)
    r = env.client.post("/video-sources/upload", headers=env.h(owner), data=form,
                        files={"file": ("a.mp4", b"x" * 10, "video/mp4")})
    assert r.status_code == 507
    env.db.query(VideoSource).delete(); env.db.commit()

    # file melebihi sisa kuota (1 MB)
    r = env.client.post("/video-sources/upload", headers=env.h(owner), data=form,
                        files={"file": ("a.mp4", b"x" * (2 * 1024 * 1024), "video/mp4")})
    assert r.status_code == 507
    assert list((env.root / "up").iterdir()) == []                # tidak ada file setengah jadi

    # kuota 0 = tanpa batas: lolos kuota, baru gagal di validasi isi video
    monkeypatch.setattr(settings, "storage_quota_mb", 0)
    r = env.client.post("/video-sources/upload", headers=env.h(owner), data=form,
                        files={"file": ("a.mp4", b"x" * (2 * 1024 * 1024), "video/mp4")})
    assert r.status_code == 422


def test_storage_usage_dan_cleanup_khusus_admin(env, monkeypatch):
    monkeypatch.setattr(settings, "snapshot_retention_days", 90)
    owner, admin = env.user("owner"), env.user("admin1", "admin")
    sess = env.session(env.source(owner))
    env.log(sess, age_days=100, content=b"12345")
    env.log(sess, age_days=1, content=b"123")
    env.source(owner, "video_upload", file_path="x", file_size=512 * 1024)

    assert env.client.get("/storage/usage", headers=env.h(owner)).status_code == 403
    assert env.client.post("/storage/cleanup", headers=env.h(owner)).status_code == 403

    u = env.client.get("/storage/usage", headers=env.h(admin)).json()
    assert u["uploads_bytes"] == 512 * 1024 and u["uploads_count"] == 1
    assert u["quota_bytes"] == settings.storage_quota_mb * 1024 * 1024
    assert u["snapshots_count"] == 2 and u["snapshots_bytes"] == 8
    assert u["retention"]["snapshot_retention_days"] == 90

    r = env.client.post("/storage/cleanup", headers=env.h(admin)).json()
    assert r["old_snapshots"] == 1
    assert env.client.get("/storage/usage", headers=env.h(admin)).json()["snapshots_count"] == 1
    assert env.db.query(ActivityLog).filter(ActivityLog.action == "storage.cleanup").count() == 1


# =====================================================================
# 9. Sesi 30 menit tidak aktif + ganti password sendiri
# =====================================================================
def test_session_age_exceeded_murni():
    now = 1_000_000.0
    limit = settings.session_max_minutes * 60
    assert session_age_exceeded({"auth_time": now - limit + 10}, now=now) is False
    assert session_age_exceeded({"auth_time": now - limit - 10}, now=now) is True
    assert session_age_exceeded({}, now=now) is False          # token lama tanpa auth_time


def test_default_umur_token_30_menit():
    assert settings.access_token_expire_minutes == 30
    payload = jwt.decode(create_access_token({"sub": "x"}), settings.secret_key, algorithms=[settings.algorithm])
    assert 29 * 60 < payload["exp"] - time.time() <= 30 * 60 and "auth_time" in payload


def test_login_mengembalikan_expires_in(env):
    env.user("budi")
    r = env.client.post("/auth/login", data={"username": "budi", "password": "rahasia123"})
    assert r.status_code == 200 and r.json()["expires_in"] == settings.access_token_expire_minutes * 60


def test_refresh_menukar_token_dan_mempertahankan_auth_time(env):
    u = env.user("budi")
    login_at = time.time() - 600
    old = create_access_token({"sub": str(u.id)}, auth_time=login_at)
    r = env.client.post("/auth/refresh", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 200
    new = r.json()["access_token"]
    p_old = jwt.decode(old, settings.secret_key, algorithms=[settings.algorithm])
    p_new = jwt.decode(new, settings.secret_key, algorithms=[settings.algorithm])
    assert p_new["jti"] != p_old["jti"] and p_new["auth_time"] == int(login_at)
    assert p_new["exp"] >= p_old["exp"]
    assert env.client.get("/auth/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_refresh_ditolak_setelah_batas_sesi_atau_token_expired(env):
    u = env.user("budi")
    too_old = create_access_token({"sub": str(u.id)}, auth_time=time.time() - (settings.session_max_minutes + 1) * 60)
    r = env.client.post("/auth/refresh", headers={"Authorization": f"Bearer {too_old}"})
    assert r.status_code == 401 and "login ulang" in r.json()["detail"]

    expired = jwt.encode({"sub": str(u.id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1), "jti": "j"},
                         settings.secret_key, algorithm=settings.algorithm)
    assert env.client.post("/auth/refresh", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    assert env.client.post("/auth/refresh").status_code == 401


def test_refresh_ditolak_untuk_akun_nonaktif_atau_token_logout(env):
    u = env.user("budi")
    h = env.h(u)
    assert env.client.post("/auth/logout", headers=h).status_code == 204
    assert env.client.post("/auth/refresh", headers=h).status_code == 401
    u2 = env.user("dina")
    h2 = env.h(u2)
    u2.status = "inactive"; env.db.commit()
    assert env.client.post("/auth/refresh", headers=h2).status_code == 403


def test_ganti_password_sukses(env):
    u = env.user("budi")
    body = {"current_password": "rahasia123", "new_password": "baru123456", "confirm_password": "baru123456"}
    assert env.client.post("/auth/change-password", headers=env.h(u), json=body).status_code == 204
    assert env.client.post("/auth/login", data={"username": "budi", "password": "baru123456"}).status_code == 200
    assert env.client.post("/auth/login", data={"username": "budi", "password": "rahasia123"}).status_code == 401
    log = env.db.query(ActivityLog).filter(ActivityLog.action == "auth.change_password").one()
    assert "baru123456" not in (log.detail or "")


def test_ganti_password_validasi(env):
    u = env.user("budi")
    h = env.h(u)
    url = "/auth/change-password"
    salah = {"current_password": "salahsalah", "new_password": "baru123456", "confirm_password": "baru123456"}
    assert env.client.post(url, headers=h, json=salah).status_code == 400       # bukan 401: sesi tidak habis
    beda = {"current_password": "rahasia123", "new_password": "baru123456", "confirm_password": "lain1234567"}
    assert env.client.post(url, headers=h, json=beda).status_code == 422
    sama = {"current_password": "rahasia123", "new_password": "rahasia123", "confirm_password": "rahasia123"}
    assert env.client.post(url, headers=h, json=sama).status_code == 422
    pendek = {"current_password": "rahasia123", "new_password": "pendek", "confirm_password": "pendek"}
    assert env.client.post(url, headers=h, json=pendek).status_code == 422
    assert env.client.post(url, json=pendek).status_code == 401