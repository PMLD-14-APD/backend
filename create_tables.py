"""
Jalankan sekali buat bikin semua tabel di database sesuai model.
    python create_tables.py

Catatan: ini cara cepat buat development. Kalau project udah jalan lama
dan sering ubah schema, sebaiknya migrasi ke Alembic biar ada history migration.
"""

from app.core.database import Base, engine

# import semua model biar ke-register ke Base.metadata
from app.models import user, environment, camera, ai_model, detection_log  # noqa: F401

if __name__ == "__main__":
    print("Membuat tabel...")
    Base.metadata.create_all(bind=engine)
    print("Selesai. Tabel yang dibuat:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
