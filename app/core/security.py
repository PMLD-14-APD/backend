import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
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


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token tidak valid atau expired",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_token_payload(token: str = Depends(oauth2_scheme)) -> dict:
    """Dependency: decode token dan pastikan belum logout. Return payload (sub, exp, jti)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise _credentials_exception()
    if is_revoked(payload.get("jti")):
        raise _credentials_exception()
    return payload


def get_current_user(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> User:
    """Dependency: pasang ini di endpoint yang wajib login."""
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


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency tambahan: pasang ini di endpoint yang khusus admin."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya admin yang boleh akses ini")
    return current_user