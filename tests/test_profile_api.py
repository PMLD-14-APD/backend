"""Tes aturan profil: username terkunci untuk admin/user, super admin boleh ubah username + password."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.user import User


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, ActivityLog.__table__])
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    db = Session()

    def make(username, role="user", status="active"):
        u = User(name=username.title(), username=username, password_hash=hash_password("rahasia123"),
                 role=role, status=status)
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    def auth(user):
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}

    yield TestClient(app), make, auth, db
    app.dependency_overrides.clear()
    db.close()


# ---------- /auth/me ----------

def test_me_menampilkan_can_edit_username(env):
    c, make, auth, _ = env
    assert c.get("/auth/me", headers=auth(make("sa", "super_admin"))).json()["can_edit_username"] is True
    assert c.get("/auth/me", headers=auth(make("ad", "admin"))).json()["can_edit_username"] is False
    assert c.get("/auth/me", headers=auth(make("us", "user"))).json()["can_edit_username"] is False


def test_admin_dan_user_tidak_bisa_ubah_username_sendiri(env):
    c, make, auth, _ = env
    for role in ("admin", "user"):
        u = make(f"{role}1", role)
        r = c.patch("/auth/me", headers=auth(u), json={"username": "baru"})
        assert r.status_code == 403
    assert c.patch("/auth/me", json={"username": "baru"}).status_code == 401


def test_super_admin_ubah_username_sendiri(env):
    c, make, auth, db = env
    sa = make("sa", "super_admin")
    make("dipakai", "user")
    h = auth(sa)
    r = c.patch("/auth/me", headers=h, json={"username": "  SuperBaru "})
    assert r.status_code == 200 and r.json()["username"] == "superbaru"
    assert c.get("/auth/me", headers=h).json()["username"] == "superbaru"   # token lama tetap valid
    assert c.post("/auth/login", data={"username": "superbaru", "password": "rahasia123"}).status_code == 200
    assert c.patch("/auth/me", headers=h, json={"username": "dipakai"}).status_code == 400
    assert c.patch("/auth/me", headers=h, json={"username": "a b"}).status_code == 422
    assert db.query(ActivityLog).filter(ActivityLog.action == "auth.update_profile").count() == 1


def test_semua_role_bisa_ganti_password_sendiri(env):
    c, make, auth, _ = env
    for role in ("super_admin", "admin", "user"):
        u = make(f"{role}x", role)
        r = c.post("/auth/change-password", headers=auth(u),
                   json={"current_password": "rahasia123", "new_password": "passbaru123", "confirm_password": "passbaru123"})
        assert r.status_code == 204
        assert c.post("/auth/login", data={"username": u.username, "password": "passbaru123"}).status_code == 200


# ---------- /users (kelola user lain) ----------

def test_admin_tidak_bisa_ubah_username_lewat_users_termasuk_dirinya(env):
    c, make, auth, _ = env
    admin = make("admin1", "admin")
    target = make("target")
    h = auth(admin)
    assert c.patch(f"/users/{target.id}", headers=h, json={"username": "baru"}).status_code == 403
    assert c.patch(f"/users/{admin.id}", headers=h, json={"username": "baru"}).status_code == 403   # tidak bisa lewat jalur ini
    # username sama dengan yang lama = tidak berubah, jadi form yang mengirim ulang username tetap lolos
    r = c.patch(f"/users/{target.id}", headers=h, json={"username": "target", "name": "Nama Baru"})
    assert r.status_code == 200 and r.json()["name"] == "Nama Baru"
    # reset password tetap boleh
    r = c.patch(f"/users/{target.id}", headers=h, json={"password": "passbaru123", "confirm_password": "passbaru123"})
    assert r.status_code == 200


def test_super_admin_bisa_ubah_username_dan_password_user_lain(env):
    c, make, auth, _ = env
    sa = make("sa", "super_admin")
    target = make("target")
    r = c.patch(f"/users/{target.id}", headers=auth(sa),
                json={"username": "baru", "password": "passbaru123", "confirm_password": "passbaru123"})
    assert r.status_code == 200 and r.json()["username"] == "baru"
    assert c.post("/auth/login", data={"username": "baru", "password": "passbaru123"}).status_code == 200


def test_admin_tidak_bisa_menyentuh_akun_super_admin(env):
    c, make, auth, _ = env
    admin = make("admin1", "admin")
    sa = make("sa", "super_admin")
    make("sa2", "super_admin")
    h = auth(admin)
    pw = {"password": "passbaru123", "confirm_password": "passbaru123"}
    assert c.patch(f"/users/{sa.id}", headers=h, json=pw).status_code == 403          # cegah ambil alih akun
    assert c.patch(f"/users/{sa.id}", headers=h, json={"role": "user"}).status_code == 403
    assert c.post(f"/users/{sa.id}/deactivate", headers=h).status_code == 403
    assert c.delete(f"/users/{sa.id}", headers=h).status_code == 403


def test_admin_tidak_bisa_membuat_atau_mengangkat_super_admin(env):
    c, make, auth, _ = env
    admin = make("admin1", "admin")
    target = make("target")
    h = auth(admin)
    body = {"name": "X", "username": "xx1", "password": "rahasia123", "confirm_password": "rahasia123", "role": "super_admin"}
    assert c.post("/users/", headers=h, json=body).status_code == 403
    assert c.patch(f"/users/{target.id}", headers=h, json={"role": "super_admin"}).status_code == 403
    sa = make("sa", "super_admin")
    assert c.post("/users/", headers=auth(sa), json=body).status_code == 201
    assert c.patch(f"/users/{target.id}", headers=auth(sa), json={"role": "super_admin"}).status_code == 200


def test_super_admin_terakhir_dilindungi(env):
    c, make, auth, db = env
    sa1 = make("sa1", "super_admin")
    sa2 = make("sa2", "super_admin")
    assert c.post(f"/users/{sa2.id}/deactivate", headers=auth(sa1)).status_code == 200   # sa1 masih ada
    # sa1 kini satu-satunya super admin aktif: guard menolak
    from fastapi import HTTPException
    from app.api.users import _guard_last_super_admin
    with pytest.raises(HTTPException) as e:
        _guard_last_super_admin(db, sa1)
    assert e.value.status_code == 400


# ---------- super admin punya hak admin ----------

def test_super_admin_punya_akses_admin(env):
    c, make, auth, _ = env
    sa = make("sa", "super_admin")
    assert c.get("/users/", headers=auth(sa)).status_code == 200
    assert c.get("/activity-logs/", headers=auth(sa)).status_code == 200
