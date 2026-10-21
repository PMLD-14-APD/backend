"""
Hapus SEMUA tabel di database (khusus development!).
    python reset_db.py
"""

from sqlalchemy import text

from app.core.database import Base, engine
from app.models import user, activity_log, environment, ai_model, camera, detection_log  # noqa: F401

if __name__ == "__main__":
    db_name = engine.url.database
    confirm = input(f"Ini akan MENGHAPUS SEMUA tabel di database '{db_name}'. Lanjut? (y/n): ")
    if confirm.strip().lower() != "y":
        print("Dibatalkan.")
    else:
        Base.metadata.drop_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS admin_logs CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        print("Selesai. Semua tabel sudah dihapus.")
