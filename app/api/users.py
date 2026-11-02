import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, require_admin
from app.models.activity_log import log_activity
from app.models.user import User
from app.schemas.user import RejectRequest, UserCreate, UserOut, UserPage, UserRole, UserStatus, UserUpdate
from app.services.history import escape_like
from app.services.users import leaves_no_active_admin

router = APIRouter()

SortOrder = Literal["desc", "asc"]


def _get_target(db: Session, user_id: uuid.UUID) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status == "deleted":
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return user


def _forbid_self(admin: User, target: User) -> None:
    if admin.id == target.id:
        raise HTTPException(status_code=400, detail="Tidak bisa melakukan aksi ini ke akun sendiri")


def _guard_last_admin(db: Session, target: User) -> None:
    """Tolak aksi yang membuat sistem tidak punya admin aktif lagi.

    Baris semua admin aktif dikunci (FOR UPDATE) sampai transaksi selesai, jadi dua admin yang
    saling menonaktifkan di saat bersamaan tetap tidak bisa lolos berdua."""
    if target.role != "admin" or target.status != "active":
        return
    active_admin_ids = [
        row.id
        for row in db.query(User.id)
        .filter(User.role == "admin", User.status == "active")
        .order_by(User.id)
        .with_for_update()
        .all()
    ]
    if leaves_no_active_admin(active_admin_ids, target.id):
        raise HTTPException(
            status_code=400,
            detail="Ini satu-satunya admin aktif. Jadikan user lain admin dulu sebelum melanjutkan",
        )


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


@router.get("/", response_model=UserPage)
def list_users(
    search: Optional[str] = Query(None, description="Cari nama atau username"),
    status_filter: Optional[UserStatus] = Query(None, alias="status"),
    role: Optional[UserRole] = None,
    sort_order: SortOrder = "desc",
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Daftar user (urut berdasarkan waktu dibuat). Tanpa filter status, user 'deleted' tidak ikut ditampilkan."""
    q = db.query(User)
    if status_filter:
        q = q.filter(User.status == status_filter)
    else:
        q = q.filter(User.status != "deleted")
    if role:
        q = q.filter(User.role == role)
    if search and search.strip():
        like = f"%{escape_like(search.strip())}%"
        q = q.filter(User.name.ilike(like, escape="\\") | User.username.ilike(like, escape="\\"))

    total = q.count()
    if sort_order == "desc":
        q = q.order_by(User.created_at.desc(), User.id.desc())
    else:
        q = q.order_by(User.created_at.asc(), User.id.asc())
    items = q.offset(offset).limit(limit).all()
    return UserPage(total=total, limit=limit, offset=offset, items=items)


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


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return _get_target(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Ubah nama, username, role, atau reset password. Hanya field yang dikirim yang diproses."""
    user = _get_target(db, user_id)
    data = payload.model_dump(exclude_unset=True, exclude={"confirm_password"})
    if not data:
        raise HTTPException(status_code=400, detail="Tidak ada data yang diubah")

    changed: list[str] = []

    if "name" in data and data["name"] != user.name:
        user.name = data["name"]
        changed.append("name")

    if "username" in data and data["username"] != user.username:
        taken = db.query(User.id).filter(User.username == data["username"], User.id != user.id).first()
        if taken:
            raise HTTPException(status_code=400, detail="Username sudah dipakai")
        changed.append(f"username ({user.username} -> {data['username']})")
        user.username = data["username"]

    if "role" in data and data["role"] != user.role:
        _forbid_self(admin, user)   # admin tidak boleh mengubah role-nya sendiri
        if user.role == "admin":    # turun dari admin ke user
            _guard_last_admin(db, user)
        changed.append(f"role ({user.role} -> {data['role']})")
        user.role = data["role"]

    if "password" in data:
        user.password_hash = hash_password(data["password"])
        changed.append("password")  # isi password tidak pernah masuk log

    if not changed:
        return user

    log_activity(db, admin.id, "user.update", "user", user.id, f"{user.username} | diubah: {', '.join(changed)}")
    try:
        db.commit()
    except IntegrityError:   # dua request ganti username yang sama bersamaan
        db.rollback()
        raise HTTPException(status_code=400, detail="Username sudah dipakai")
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
    _guard_last_admin(db, user)
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
    _guard_last_admin(db, user)
    return _transition(
        db, admin, user, {"pending", "active", "rejected", "inactive"}, "deleted", "user.delete"
    )