"""Tes filter /history/violations (SQLite in-memory)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import activity_log, ai_model, analysis, environment, user, video_source  # noqa: F401
from app.models.ai_model import AIModel, ApdClass
from app.models.analysis import AnalysisSession, DetectionLog, DetectionLogItem
from app.models.environment import Environment, Location
from app.models.user import User
from app.models.video_source import VideoSource


@pytest.fixture()
def env():
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

    admin = User(name="A", username="admin1", password_hash=hash_password("rahasia123"), role="admin", status="active")
    environment_ = Environment(name="Konstruksi")
    loc = Location(name="Gudang A")
    helm, vest = ApdClass(name="Helm", label_key="helmet"), ApdClass(name="Rompi", label_key="vest")
    db.add_all([admin, environment_, loc, helm, vest])
    db.commit()
    model = AIModel(environment_id=environment_.id, name="yolo", version="1", weights_path="x.pt")
    db.add(model)
    db.commit()
    src = VideoSource(user_id=admin.id, location_id=loc.id, environment_id=environment_.id, name="Cam 1",
                      source_type="cctv_stream", status="active")
    db.add(src)
    db.commit()
    ses = AnalysisSession(source_id=src.id, model_id=model.id, user_id=admin.id, status="done")
    db.add(ses)
    db.commit()

    counter = [0]

    def add_log(violation_type, status="kurang_lengkap"):
        counter[0] += 1
        log = DetectionLog(id=counter[0], session_id=ses.id, track_id=1, compliance_status=status,
                           violation_type=violation_type, confidence=0.9, frame_number=1, video_timestamp=1.0,
                           bbox={}, detected_at=datetime(2026, 11, 20, counter[0], 0, tzinfo=timezone.utc))
        db.add(log)
        db.commit()

    add_log("NO_HELMET")
    add_log("NO_VEST")
    add_log("NO_HELMET,NO_VEST", "tidak_digunakan")
    add_log("NO_HELMET_STRAP")      # mirip NO_HELMET tapi APD lain

    headers = {"Authorization": f"Bearer {create_access_token({'sub': str(admin.id)})}"}
    yield TestClient(app), headers
    app.dependency_overrides.clear()
    db.close()


def types(env, qs):
    c, h = env
    r = c.get(f"/history/violations?{qs}", headers=h)
    assert r.status_code == 200, r.text
    return sorted(i["violation_type"] for i in r.json()["items"])


def test_tanpa_filter_semua_muncul(env):
    assert len(types(env, "")) == 4


def test_filter_violation_type_termasuk_pelanggaran_gabungan(env):
    assert types(env, "violation_type=NO_HELMET") == ["NO_HELMET", "NO_HELMET,NO_VEST"]
    assert types(env, "violation_type=NO_VEST") == ["NO_HELMET,NO_VEST", "NO_VEST"]


def test_filter_tidak_menangkap_token_yang_hanya_mirip(env):
    assert "NO_HELMET_STRAP" not in types(env, "violation_type=NO_HELMET")
    assert types(env, "violation_type=NO_HELMET_STRAP") == ["NO_HELMET_STRAP"]


def test_filter_menerima_label_key_dan_huruf_kecil(env):
    assert types(env, "violation_type=helmet") == ["NO_HELMET", "NO_HELMET,NO_VEST"]
    assert types(env, "violation_type=%20no_vest%20") == ["NO_HELMET,NO_VEST", "NO_VEST"]


def test_violation_type_kosong_berarti_tanpa_filter(env):
    assert len(types(env, "violation_type=")) == 4


def test_violation_type_tak_ada_hasilnya_kosong(env):
    assert types(env, "violation_type=NO_GLOVES") == []


def test_wildcard_diketik_apa_adanya(env):
    assert types(env, "violation_type=%25") == []
    assert types(env, "violation_type=NO_%25") == []


def test_bisa_digabung_dengan_filter_lain(env):
    assert types(env, "violation_type=NO_HELMET&compliance_status=tidak_digunakan") == ["NO_HELMET,NO_VEST"]
    assert types(env, "violation_type=NO_HELMET&date_from=2026-11-21&date_to=2026-11-21") == []
