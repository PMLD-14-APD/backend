"""
Jalankan sekali buat bikin semua tabel di database sesuai model.
    python create_tables.py

Catatan: ini cara cepat buat development. create_all TIDAK mengubah tabel yang
sudah ada. Kalau schema berubah, drop tabelnya dulu atau migrasi ke Alembic.
"""

from app.core.database import Base, engine

# import semua model biar ke-register ke Base.metadata
from app.models import user, activity_log, environment, camera, ai_model, detection_log  # noqa: F401

if __name__ == "__main__":
    print("Membuat tabel...")
    Base.metadata.create_all(bind=engine)
    print("Selesai. Tabel yang dibuat:")
    for table in Base.metadata.tables:
        print(f"  - {table}")