from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    get_current_user,
    get_token_payload,
    hash_password,
    revoke_token,
    session_age_exceeded,
    verify_password,
)
from app.models.activity_log import log_activity
from app.models.user import User
from app.schemas.auth import PasswordChange, Token, UserOut, UserRegister

router = APIRouter()

# pesan untuk user yang password-nya benar tapi akunnya belum/tidak bisa dipakai
BLOCKED_STATUS_MESSAGES = {
    "pending": "Akun kamu masih menunggu persetujuan admin",
    "rejected": "Pendaftaran akun kamu ditolak admin",
    "inactive": "Akun kamu dinonaktifkan. Hubungi admin",
}


def _token_response(access_token: str) -> dict:
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
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

    return _token_response(create_access_token(data={"sub": str(user.id)}))


@router.post("/refresh", response_model=Token)
def refresh(
    token_payload: dict = Depends(get_token_payload),
    current_user: User = Depends(get_current_user),
):
    """Perpanjang sesi: tukar token yang MASIH berlaku dengan token baru (umur penuh lagi).
    Frontend memanggil ini saat ada aktivitas pengguna. Kalau pengguna diam lebih lama dari
    ACCESS_TOKEN_EXPIRE_MINUTES, token mati dan harus login ulang. Total umur sesi dibatasi
    SESSION_MAX_MINUTES sejak login awal."""
    if session_age_exceeded(token_payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi sudah mencapai batas waktu, silakan login ulang",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        data={"sub": str(current_user.id)}, auth_time=token_payload.get("auth_time")
    )
    return _token_response(token)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ganti password akun sendiri. Password lama salah dijawab 400 (bukan 401) supaya frontend
    tidak mengira sesinya habis lalu logout otomatis."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password lama salah")
    current_user.password_hash = hash_password(payload.new_password)
    log_activity(db, current_user.id, "auth.change_password", "user", current_user.id, current_user.username)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    token_payload: dict = Depends(get_token_payload),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Akhiri sesi: token yang dipakai request ini langsung tidak berlaku lagi.
    Frontend tetap harus menghapus token dari penyimpanan klien setelah memanggil ini."""
    jti = token_payload.get("jti")
    if jti:   # token lama (sebelum ada jti) tidak bisa dicabut, hanya habis sendiri
        revoke_token(jti, token_payload["exp"])
    log_activity(db, current_user.id, "auth.logout", "user", current_user.id, current_user.username)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Endpoint buat tes: kalau ini berhasil, berarti token kamu valid."""
    return current_user