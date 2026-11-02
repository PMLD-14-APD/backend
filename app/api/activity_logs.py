"""Log aktivitas sistem (khusus admin): siapa melakukan apa, kapan."""
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.history import date_range
from app.core.database import get_db
from app.core.security import require_admin
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.schemas.activity_log import ActivityLogItem, ActivityLogPage
from app.services.history import escape_like

router = APIRouter(prefix="/activity-logs", tags=["Log Aktivitas (Admin)"])

SortOrder = Literal["desc", "asc"]


@router.get("/", response_model=ActivityLogPage)
def list_activity_logs(
    user_id: Optional[uuid.UUID] = Query(None, description="Pelaku aksi"),
    action: Optional[str] = Query(
        None, description="Aksi persis (mis. user.approve), atau awalan dengan '.*' (mis. user.*)"
    ),
    target_type: Optional[str] = Query(None, description="Mis. user, video_source"),
    search: Optional[str] = Query(None, description="Cari di kolom detail (username/nama target)"),
    rng: tuple = Depends(date_range),
    sort_order: SortOrder = "desc",
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    start, end = rng
    query = db.query(ActivityLog, User.name, User.username).outerjoin(User, User.id == ActivityLog.user_id)

    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    if action:
        if action.endswith(".*"):
            prefix = escape_like(action[:-1])   # sisakan titiknya: 'user.' bukan 'user'
            query = query.filter(ActivityLog.action.like(f"{prefix}%", escape="\\"))
        else:
            query = query.filter(ActivityLog.action == action)
    if target_type:
        query = query.filter(ActivityLog.target_type == target_type)
    if search and search.strip():
        query = query.filter(ActivityLog.detail.ilike(f"%{escape_like(search.strip())}%", escape="\\"))
    if start:
        query = query.filter(ActivityLog.created_at >= start)
    if end:
        query = query.filter(ActivityLog.created_at < end)

    total = query.count()
    if sort_order == "desc":
        query = query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
    else:
        query = query.order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
    rows = query.offset(offset).limit(limit).all()

    items = [
        ActivityLogItem(
            id=log.id, user_id=log.user_id, user_name=name, username=username, action=log.action,
            target_type=log.target_type, target_id=log.target_id, detail=log.detail,
            created_at=log.created_at,
        )
        for log, name, username in rows
    ]
    return ActivityLogPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/actions", response_model=list[str])
def list_activity_actions(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Daftar nilai `action` yang pernah tercatat, buat isi dropdown filter di frontend."""
    rows = db.query(ActivityLog.action).distinct().order_by(ActivityLog.action).all()
    return [r[0] for r in rows]