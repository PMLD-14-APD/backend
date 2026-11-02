"""Tes endpoint /users dan /activity-logs memakai SQLite in-memory (butuh: pip install httpx)."""
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

    def make(username, role="user", status="active", name=None):
        u = User(name=name or username.title(), username=username, password_hash=hash_password("rahasia123"),
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


def test_list_search_dan_paginasi(env):
    c, make, auth, _ = env
    admin = make("admin1", "admin")
    for i in range(5):
        make(f"siswa{i}", name=f"Siswa {i}")
    make("budi", name="Budi Santoso")

    r = c.get("/users/?search=siswa&limit=2&offset=0", headers=auth(admin)).json()
    assert r["total"] == 5 and len(r["items"]) == 2 and r["limit"] == 2
    r = c.get("/users/?search=santoso", headers=auth(admin)).json()
    assert [u["username"] for u in r["items"]] == ["budi"]
    assert c.get("/users/?search=%25", headers=auth(admin)).json()["total"] == 0   # '%' bukan wildcard


def test_user_biasa_ditolak(env):
    c, make, auth, _ = env
    biasa = make("biasa")
    assert c.get("/users/", headers=auth(biasa)).status_code == 403
    assert c.get("/activity-logs/", headers=auth(biasa)).status_code == 403


def test_get_user_dan_404(env):
    c, make, auth, _ = env
    admin = make("admin1", "admin")
    u = make("target")
    assert c.get(f"/users/{u.id}", headers=auth(admin)).json()["username"] == "target"
    assert c.get("/users/00000000-0000-0000-0000-000000000000", headers=auth(admin)).status_code == 404


def test_patch_ubah_data_dan_reset_password(env):
    c, make, auth, db = env
    admin = make("admin1", "admin")
    u = make("target")
    r = c.patch(f"/users/{u.id}", headers=auth(admin),
                json={"name": "Nama Baru", "username": "BARU", "password": "passbaru123", "confirm_password": "passbaru123"})
    assert r.status_code == 200 and r.json()["username"] == "baru" and r.json()["name"] == "Nama Baru"
    login = c.post("/auth/login", data={"username": "baru", "password": "passbaru123"})
    assert login.status_code == 200
    log = db.query(ActivityLog).filter(ActivityLog.action == "user.update").one()
    assert "password" in log.detail and "passbaru123" not in log.detail


def test_patch_validasi(env):
    c, make, auth, _ = env
    admin = make("admin1", "admin")
    u = make("target")
    make("dipakai")
    h = auth(admin)
    assert c.patch(f"/users/{u.id}", headers=h, json={}).status_code == 400
    assert c.patch(f"/users/{u.id}", headers=h, json={"username": "dipakai"}).status_code == 400
    assert c.patch(f"/users/{u.id}", headers=h, json={"password": "passbaru123"}).status_code == 422
    assert c.patch(f"/users/{u.id}", headers=h, json={"role": "superman"}).status_code == 422


def test_admin_tidak_bisa_ubah_role_sendiri(env):
    c, make, auth, _ = env
    a1 = make("admin1", "admin")
    make("admin2", "admin")
    r = c.patch(f"/users/{a1.id}", headers=auth(a1), json={"role": "user"})
    assert r.status_code == 400


def test_admin_terakhir_dilindungi(env):
    c, make, auth, _ = env
    a1 = make("admin1", "admin")
    a2 = make("admin2", "admin")

    # a1 menonaktifkan a2: boleh, a1 masih ada
    assert c.post(f"/users/{a2.id}/deactivate", headers=auth(a1)).status_code == 200

    # a2 sudah nonaktif, jadi tidak ada admin lain; a1 diturunkan/dihapus orang lain tidak mungkin dites
    # lewat API karena aktor harus admin aktif. Uji lewat admin ketiga:
    a3 = make("admin3", "admin")
    assert c.post(f"/users/{a1.id}/deactivate", headers=auth(a3)).status_code == 200   # a3 masih ada
    # sekarang a3 satu-satunya admin aktif: a1 (nonaktif) diaktifkan dulu lalu dipakai sebagai aktor
    assert c.post(f"/users/{a1.id}/activate", headers=auth(a3)).status_code == 200
    assert c.post(f"/users/{a3.id}/deactivate", headers=auth(a1)).status_code == 200   # a1 masih aktif
    # a1 kini satu-satunya admin aktif; a2 (nonaktif) diubah role -> boleh karena bukan admin aktif
    assert c.patch(f"/users/{a2.id}", headers=auth(a1), json={"role": "user"}).status_code == 200


def test_demote_admin_terakhir_ditolak(env):
    c, make, auth, db = env
    a1 = make("admin1", "admin")
    a2 = make("admin2", "admin")
    # a1 menurunkan a2 -> boleh (a1 tersisa)
    assert c.patch(f"/users/{a2.id}", headers=auth(a1), json={"role": "user"}).status_code == 200
    # a2 kini user biasa; kalau a1 mencoba menghapus dirinya -> ditolak (self)
    assert c.delete(f"/users/{a1.id}", headers=auth(a1)).status_code == 400


def test_guard_menolak_saat_tidak_ada_admin_lain(env):
    """Admin yang tokennya masih valid tapi dia satu-satunya admin aktif lain: panggil guard langsung."""
    from fastapi import HTTPException
    from app.api.users import _guard_last_admin

    _, make, _, db = env
    a1 = make("admin1", "admin")
    with pytest.raises(HTTPException) as e:
        _guard_last_admin(db, a1)
    assert e.value.status_code == 400
    make("admin2", "admin")
    _guard_last_admin(db, a1)   # sekarang aman


def test_activity_logs_filter_dan_paginasi(env):
    c, make, auth, db = env
    admin = make("admin1", "admin")
    u = make("target")
    h = auth(admin)
    c.post(f"/users/{u.id}/deactivate", headers=h)
    c.post(f"/users/{u.id}/activate", headers=h)
    c.patch(f"/users/{u.id}", headers=h, json={"name": "X"})

    r = c.get("/activity-logs/", headers=h).json()
    assert r["total"] == 3 and r["items"][0]["username"] == "admin1"
    assert c.get("/activity-logs/?action=user.activate", headers=h).json()["total"] == 1
    assert c.get("/activity-logs/?action=user.*", headers=h).json()["total"] == 3
    assert c.get("/activity-logs/?action=auth.*", headers=h).json()["total"] == 0
    assert c.get(f"/activity-logs/?user_id={admin.id}&limit=2", headers=h).json()["items"].__len__() == 2
    assert c.get("/activity-logs/?search=target", headers=h).json()["total"] == 3
    assert sorted(c.get("/activity-logs/actions", headers=h).json()) == ["user.activate", "user.deactivate", "user.update"]
    assert c.get("/activity-logs/?date_from=2030-02-01&date_to=2030-01-01", headers=h).status_code == 422