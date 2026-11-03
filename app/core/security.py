import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl ini cuma buat dokumentasi /docs, biar Swagger tau harus panggil endpoint mana buat login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
# versi yang tidak langsung 401 kalau header Authorization kosong (dipakai endpoint yang juga menerima ?token=)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


# ----------------------------------------------------------------------
# Denylist token (logout)
# ----------------------------------------------------------------------
# JWT itu stateless, jadi "logout" = mencatat jti token ke daftar tolak sampai token itu kedaluwarsa.
# Disimpan di memori proses: cocok dengan desain MVP (satu worker uvicorn, manager inferensi juga
# di memori). Konsekuensi: daftar ini hilang kalau server restart, dan tidak dibagi antar worker.
# Kalau nanti perlu tahan restart / multi-worker, pindahkan ke tabel DB atau Redis (fungsi di
# bawah ini satu-satunya tempat yang perlu diubah).
_revoked: dict[str, float] = {}      # jti -> waktu kedaluwarsa token (epoch detik)
_revoked_lock = threading.Lock()


def revoke_token(jti: str, exp: float) -> None:
    """Tandai token sebagai sudah logout. Entri yang tokennya sudah kedaluwarsa dibuang sekalian."""
    now = time.time()
    with _revoked_lock:
        for key in [k for k, v in _revoked.items() if v <= now]:
            del _revoked[key]
        _revoked[jti] = float(exp)


def is_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    with _revoked_lock:
        exp = _revoked.get(jti)
        if exp is None:
            return False
        if exp <= time.time():
            del _revoked[jti]
            return False
        return True


# ----------------------------------------------------------------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, auth_time: Optional[float] = None) -> str:
    """Buat JWT. `auth_time` = waktu login awal (epoch detik); dibawa terus saat refresh supaya
    total umur sesi bisa dibatasi (SESSION_MAX_MINUTES)."""
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    to_encode.update({
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": uuid.uuid4().hex,
        "auth_time": int(auth_time if auth_time is not None else now.timestamp()),
    })
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def session_age_exceeded(payload: dict, now: Optional[float] = None) -> bool:
    """True kalau login awal sudah lebih lama dari SESSION_MAX_MINUTES (wajib login ulang).
    Token lama tanpa `auth_time` dianggap belum melewati batas."""
    auth_time = payload.get("auth_time")
    if auth_time is None:
        return False
    now = time.time() if now is None else now
    return now - float(auth_time) > settings.session_max_minutes * 60


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token tidak valid atau expired",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise _credentials_exception()
    if is_revoked(payload.get("jti")):
        raise _credentials_exception()
    return payload


def _load_active_user(payload: dict, db: Session) -> User:
    try:
        sub = payload.get("sub")
        if sub is None:
            raise _credentials_exception()
        user_id = uuid.UUID(sub)
    except ValueError:
        raise _credentials_exception()

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _credentials_exception()

    # user yang sudah dinonaktifkan/dihapus/ditolak tokennya langsung tidak berlaku
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun tidak aktif",
        )
    return user


def get_token_payload(token: str = Depends(oauth2_scheme)) -> dict:
    """Dependency: decode token dan pastikan belum logout. Return payload (sub, exp, jti, auth_time)."""
    return _decode_token(token)


def get_current_user(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> User:
    """Dependency: pasang ini di endpoint yang wajib login."""
    return _load_active_user(payload, db)


def get_current_user_allow_query_token(
    header_token: Optional[str] = Depends(oauth2_scheme_optional),
    token: Optional[str] = Query(None, description="Alternatif header Authorization, untuk tag <img> yang tidak bisa mengirim header"),
    db: Session = Depends(get_db),
) -> User:
    """Sama seperti get_current_user, tapi boleh juga lewat ?token=. HANYA dipakai di endpoint
    yang dibuka langsung oleh browser (foto bukti); token di URL bisa tercatat di log server/proxy."""
    raw = header_token or token
    if not raw:
        raise _credentials_exception()
    return _load_active_user(_decode_token(raw), db)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency tambahan: pasang ini di endpoint yang khusus admin."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya admin yang boleh akses ini")
    return current_user