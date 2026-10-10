"""
Drop tabel auth lama (khusus DB development!).
    python reset_auth_tables.py
"""

from sqlalchemy import text

from app.core.database import engine

if __name__ == "__main__":
    confirm = input("Ini akan menghapus tabel users, admin_logs, activity_logs. Lanjut? (y/n): ")
    if confirm.strip().lower() != "y":
        print("Dibatalkan.")
    else:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS activity_logs, admin_logs, users CASCADE"))
        print("Selesai. Tabel lama sudah dihapus.")