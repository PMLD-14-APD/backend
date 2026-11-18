"""
Bikin akun admin pertama (karena /auth/register cuma bikin user biasa berstatus pending).
    python create_admin.py                # admin biasa (username terkunci di halaman profil)
    python create_admin.py --super-admin  # super admin (boleh ubah username dan password sendiri)
"""

import argparse
import getpass
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import user, activity_log  # noqa: F401
from app.models.activity_log import log_activity
from app.models.user import User


def main():
    parser = argparse.ArgumentParser(description="Bikin akun admin / super admin")
    parser.add_argument("--super-admin", action="store_true", help="buat sebagai super admin, bukan admin biasa")
    args = parser.parse_args()
    role = "super_admin" if args.super_admin else "admin"

    name = input("Nama lengkap: ").strip()
    username = input("Username: ").strip().lower()
    password = getpass.getpass("Password (min 8 karakter): ")

    if not name or len(username) < 3 or len(password) < 8 or len(password) > 72:
        print("Input tidak valid (username min 3, password 8-72 karakter).")
        return

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            print(f"Username '{username}' sudah ada.")
            return

        admin = User(
            name=name,
            username=username,
            password_hash=hash_password(password),
            role=role,
            status="active",
            approved_at=datetime.now(timezone.utc),
        )
        db.add(admin)
        db.flush()
        log_activity(db, admin.id, "user.create", "user", admin.id, f"{admin.username} (seed {role})")
        db.commit()
        print(f"{role} '{username}' berhasil dibuat.")
    finally:
        db.close()


if __name__ == "__main__":
    main()