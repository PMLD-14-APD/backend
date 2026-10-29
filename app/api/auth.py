from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from app.models.activity_log import log_activity
from app.models.user import User
from app.schemas.auth import PasswordChange, UserRegister, UserOut, Token

router = APIRouter()

# pesan untuk user yang password-nya benar tapi akunnya belum/tidak bisa dipakai
BLOCKED_STATUS_MESSAGES = {
    "pending": "Akun kamu masih menunggu persetujuan admin",
    "rejected": "Pendaftaran akun kamu ditolak admin",
    "inactive": "Akun kamu dinonaktifkan. Hubungi admin",
}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username sudah dipakai")

    user = User(
        name=payload.name,
        username=payload.username,
        password_hash=hash_password(payload.password),
        role="user",
        status="pending",  # menunggu approval admin
    )
    db.add(user)
    db.flush()  # supaya user.id sudah terisi buat log
    log_activity(db, user.id, "user.register", "user", user.id, user.username)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # form_data.username = username (nama field standar OAuth2PasswordRequestForm)
    username = form_data.username.strip().lower()
    user = db.query(User).filter(User.username == username).first()

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Username atau password salah",
    )
    if not user or not verify_password(form_data.password, user.password_hash):
        raise invalid

    # status baru dicek setelah password benar, supaya status akun orang lain tidak bocor
    if user.status == "deleted":
        raise invalid
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=BLOCKED_STATUS_MESSAGES.get(user.status, "Akun tidak aktif"),
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Endpoint buat tes: kalau ini berhasil, berarti token kamu valid."""
    return current_user

@router.patch("/me/password")
def change_my_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ganti password akun sendiri (wajib mengisi password lama)."""
    # 400 (bukan 401) supaya frontend tidak mengira token habis lalu logout otomatis
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password lama salah")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail="Password baru harus berbeda dari password lama")
    current_user.password_hash = hash_password(payload.new_password)
    log_activity(db, current_user.id, "user.change_password", "user", current_user.id, current_user.username)
    db.commit()
    return {"message": "Password berhasil diubah"}