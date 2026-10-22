"""
Hapus SEMUA tabel di database (khusus development!), termasuk tabel sisa skema lama
(cameras, detection_logs lama, dll) dan alembic_version.
    python reset_db.py
Setelah itu: alembic upgrade head
"""

from sqlalchemy import inspect, text

from app.core.database import engine

if __name__ == "__main__":
    db_name = engine.url.database
    confirm = input(f"Ini akan MENGHAPUS SEMUA tabel di database '{db_name}'. Lanjut? (y/n): ")
    if confirm.strip().lower() != "y":
        print("Dibatalkan.")
    else:
        tables = inspect(engine).get_table_names()   # semua tabel yang benar-benar ada di DB
        with engine.begin() as conn:
            for name in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
        print(f"Selesai. {len(tables)} tabel dihapus: {', '.join(sorted(tables)) or '-'}")