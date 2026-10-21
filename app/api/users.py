import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, require_admin
from app.models.activity_log import log_activity
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.user import RejectRequest, UserCreate, UserRole, UserStatus

router = APIRouter()


def _get_target(db: Session, user_id: uuid.UUID) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status == "deleted":
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return user


def _forbid_self(admin: User, target: User) -> None:
    if admin.id == target.id:
        raise HTTPException(status_code=400, detail="Tidak bisa melakukan aksi ini ke akun sendiri")


def _transition(db: Session, admin: User, user: User, allowed_from: set, new_status: str,
                action: str, extra: Optional[str] = None) -> User:
    if user.status not in allowed_from:
        raise HTTPException(
            status_code=400,
            detail=f"Aksi tidak bisa dilakukan, status user sekarang '{user.status}'",
        )
    user.status = new_status
    detail = user.username if not extra else f"{user.username} | {extra}"
    log_activity(db, admin.id, action, "user", user.id, detail)
    db.commit()
    db.refresh(user)
    return user


@router.get("/", response_model=list[UserOut])
def list_users(
    status_filter: Optional[UserStatus] = Query(None, alias="status"),
    role: Optional[UserRole] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Daftar user. Tanpa filter status, user 'deleted' tidak ikut ditampilkan."""
    q = db.query(User)
    if status_filter:
        q = q.filter(User.status == status_filter)
    else:
        q = q.filter(User.status != "deleted")
    if role:
        q = q.filter(User.role == role)
    return q.order_by(User.created_at.desc()).all()


@router.post("/", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin bikin user langsung aktif (tanpa lewat approval)."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username sudah dipakai")

    user = User(
        name=payload.name,
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        status="active",
        approved_by=admin.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    log_activity(db, admin.id, "user.create", "user", user.id, user.username)
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/approve", response_model=UserOut)
def approve_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = _get_target(db, user_id)
    if user.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Hanya user pending yang bisa disetujui, status sekarang '{user.status}'",
        )
    user.approved_by = admin.id
    user.approved_at = datetime.now(timezone.utc)
    return _transition(db, admin, user, {"pending"}, "active", "user.approve")


@router.post("/{user_id}/reject", response_model=UserOut)
def reject_user(
    user_id: uuid.UUID,
    payload: RejectRequest = RejectRequest(),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = _get_target(db, user_id)
    extra = f"alasan: {payload.reason}" if payload.reason else None
    return _transition(db, admin, user, {"pending"}, "rejected", "user.reject", extra)


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = _get_target(db, user_id)
    _forbid_self(admin, user)
    return _transition(db, admin, user, {"active"}, "inactive", "user.deactivate")


@router.post("/{user_id}/activate", response_model=UserOut)
def activate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = _get_target(db, user_id)
    return _transition(db, admin, user, {"inactive"}, "active", "user.activate")


@router.delete("/{user_id}", response_model=UserOut)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Soft delete: status jadi 'deleted', barisnya tetap ada supaya riwayat tidak putus."""
    user = _get_target(db, user_id)
    _forbid_self(admin, user)
    return _transition(
        db, admin, user, {"pending", "active", "rejected", "inactive"}, "deleted", "user.delete"
    )