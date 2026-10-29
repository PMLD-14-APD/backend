"""Log aktivitas sistem (khusus admin): siapa melakukan apa, kapan, ke siapa/apa."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.history import date_range, like_pattern
from app.core.database import get_db
from app.core.security import require_admin
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.schemas.activity import ActivityLogOut
from app.schemas.history import Page

router = APIRouter(prefix="/activity-logs", tags=["Activity Logs (Admin)"])


@router.get("/actions", response_model=list[str])
def list_actions(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Daftar jenis aksi yang pernah tercatat, untuk isi dropdown filter."""
    return sorted(a for (a,) in db.query(ActivityLog.action).distinct().all())


@router.get("/", response_model=Page[ActivityLogOut])
def list_activity_logs(
    q: Optional[str] = Query(None, description="Cari di kolom detail (username / nama target)"),
    user_id: Optional[uuid.UUID] = Query(None, description="Filter berdasarkan pelaku"),
    action: Optional[str] = Query(None, description="Aksi persis, mis. user.create"),
    target_type: Optional[str] = Query(None, description="Mis. user, video_source"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    start, end = date_range(date_from, date_to)

    base = db.query(ActivityLog)
    if q and q.strip():
        base = base.filter(ActivityLog.detail.ilike(like_pattern(q), escape="\\"))
    if user_id:
        base = base.filter(ActivityLog.user_id == user_id)
    if action:
        base = base.filter(ActivityLog.action == action)
    if target_type:
        base = base.filter(ActivityLog.target_type == target_type)
    if start:
        base = base.filter(ActivityLog.created_at >= start)
    if end:
        base = base.filter(ActivityLog.created_at < end)

    total = base.count()
    rows = (
        base.outerjoin(User, ActivityLog.user_id == User.id)
        .add_columns(User.username, User.name)
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .offset(offset).limit(limit).all()
    )
    items = [
        ActivityLogOut(
            id=log.id, user_id=log.user_id, username=uname, user_name=name, action=log.action,
            target_type=log.target_type, target_id=log.target_id, detail=log.detail,
            created_at=log.created_at,
        )
        for log, uname, name in rows
    ]
    return Page(total=total, limit=limit, offset=offset, items=items)