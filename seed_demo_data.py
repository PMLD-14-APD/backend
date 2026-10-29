"""
Isi DATA DEMO supaya dashboard dan riwayat bisa dicoba tanpa menunggu model AI menghasilkan data.

    python seed_demo_data.py                  # 3 hari terakhir, pemilik = admin pertama
    python seed_demo_data.py --days 7
    python seed_demo_data.py --owner budi     # supaya user 'budi' (bukan admin) juga melihatnya
    python seed_demo_data.py --reset          # hapus data demo lama lalu buat ulang

Syarat: seed_master_data.py dan create_admin.py sudah dijalankan.
Semua sumber demo bernama awalan "Demo - " dan berstatus inactive (tidak mencoba terhubung ke kamera).
"""

import argparse
import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import user, activity_log, environment, ai_model, video_source, analysis  # noqa: F401
from app.models.ai_model import AIModel, ApdClass, EnvironmentApdClass
from app.models.analysis import AnalysisSession, ComplianceStat, DetectionLog, DetectionLogItem
from app.models.environment import Environment, Location
from app.models.user import User
from app.models.video_source import VideoSource

LOCAL_TZ = ZoneInfo(settings.dashboard_timezone)

PREFIX = "Demo - "
# (nama sumber, nama lokasi, tingkat pelanggaran relatif)
DEMO_SOURCES = [
    (PREFIX + "Gerbang Utama", "Demo Area Proyek", 1.0),
    (PREFIX + "Gudang Bahan", "Demo Gudang", 2.0),
    (PREFIX + "Area Pengecoran", "Demo Area Proyek", 1.5),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--owner", default=None, help="username pemilik sumber demo (default: admin pertama)")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    random.seed(7)
    db = SessionLocal()
    try:
        owner = (
            db.query(User).filter(User.username == args.owner.lower(), User.status == "active").first()
            if args.owner else
            db.query(User).filter(User.role == "admin", User.status == "active").order_by(User.created_at).first()
        )
        env = db.query(Environment).filter(Environment.name == "Konstruksi").first()
        apds = []
        if env:
            apds = (
                db.query(ApdClass)
                .join(EnvironmentApdClass, EnvironmentApdClass.apd_class_id == ApdClass.id)
                .filter(EnvironmentApdClass.environment_id == env.id)
                .order_by(ApdClass.label_key)
                .all()
            )
        if not (owner and env and len(apds) >= 2):
            raise SystemExit("Data dasar belum lengkap. Jalankan dulu: python seed_master_data.py dan python create_admin.py")

        model = db.query(AIModel).filter(AIModel.environment_id == env.id).first()
        if model is None:                                   # cukup placeholder, tidak dipakai inference
            model = AIModel(environment_id=env.id, name="Demo Model", version="0", weights_path="demo.pt", is_active=False)
            db.add(model)
            db.flush()

        old = db.query(VideoSource).filter(VideoSource.name.like(PREFIX + "%")).all()
        if old:
            if not args.reset:
                print("Data demo sudah ada (pakai --reset untuk membuat ulang).")
                return
            for src in old:
                db.delete(src)
            db.commit()

        now = datetime.now(timezone.utc)
        today = datetime.now(LOCAL_TZ).date()
        n_stats = n_logs = 0

        for src_name, loc_name, factor in DEMO_SOURCES:
            location = db.query(Location).filter(Location.name == loc_name).first()
            if location is None:
                location = Location(name=loc_name, address="Lokasi contoh")
                db.add(location)
                db.flush()
            source = VideoSource(
                user_id=owner.id, location_id=location.id, environment_id=env.id, name=src_name,
                source_type="cctv_stream", stream_url="rtsp://demo:demo@192.168.1.10:554/stream",
                target_fps=5, status="inactive",
            )
            db.add(source)
            db.flush()

            for back in range(args.days - 1, -1, -1):
                day = today - timedelta(days=back)
                session = AnalysisSession(
                    source_id=source.id, model_id=model.id, user_id=owner.id, status="done",
                    started_at=datetime.combine(day, time(8), tzinfo=LOCAL_TZ),
                    finished_at=datetime.combine(day, time(16), tzinfo=LOCAL_TZ),
                )
                db.add(session)
                db.flush()

                tot = vio = ok_sum = 0
                for hour in range(8, 16):                    # jam kerja 08:00 - 16:00 waktu lokal
                    bucket = datetime.combine(day, time(hour), tzinfo=LOCAL_TZ)
                    if bucket > now:                         # jangan bikin data dari masa depan
                        continue
                    tidak = min(random.randint(0, round(2 * factor)), 5)
                    kurang = min(random.randint(0, round(3 * factor)), 6)
                    lengkap = random.randint(4, 14)
                    persons = lengkap + kurang + tidak
                    db.add(ComplianceStat(
                        session_id=session.id, bucket_start=bucket, total_persons=persons,
                        lengkap=lengkap, kurang_lengkap=kurang, tidak_digunakan=tidak,
                    ))
                    n_stats += 1
                    tot, vio, ok_sum = tot + persons, vio + kurang + tidak, ok_sum + lengkap

                    for status in ["tidak_digunakan"] * tidak + ["kurang_lengkap"] * kurang:
                        if status == "tidak_digunakan":
                            missing = [a.label_key for a in apds]
                        else:
                            missing = [random.choice(apds).label_key]
                        present = {a.label_key for a in apds} - set(missing)
                        log = DetectionLog(
                            session_id=session.id, track_id=random.randint(1, 40),
                            compliance_status=status,
                            violation_type=",".join(f"NO_{k.upper()}" for k in sorted(missing)),
                            confidence=round(random.uniform(0.6, 0.97), 2),
                            frame_number=random.randint(1, 20000),
                            video_timestamp=round(random.uniform(0, 28800), 2),
                            bbox={"x": random.randint(0, 800), "y": random.randint(0, 400), "w": 90, "h": 220},
                            image_url=None,                  # foto asli baru ada setelah inference berjalan
                            detected_at=bucket + timedelta(minutes=random.randint(0, 59)),
                        )
                        db.add(log)
                        db.flush()
                        for apd in apds:
                            db.add(DetectionLogItem(
                                detection_log_id=log.id, apd_class_id=apd.id,
                                is_present=apd.label_key in present,
                                confidence=round(random.uniform(0.6, 0.97), 2) if apd.label_key in present else 0.0,
                            ))
                        n_logs += 1

                session.total_persons, session.total_violations = tot, vio
                session.compliance_rate = round(ok_sum / tot * 100, 2) if tot else None

        db.commit()
        print(f"Data demo dibuat untuk '{owner.username}': {len(DEMO_SOURCES)} sumber, "
              f"{n_stats} baris statistik per jam, {n_logs} catatan pelanggaran")
    finally:
        db.close()


if __name__ == "__main__":
    main()