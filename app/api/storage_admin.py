"""Pemakaian storage dan pembersihan manual (khusus admin)."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin
from app.models.activity_log import log_activity
from app.models.user import User
from app.models.video_source import VideoSource
from app.services.retention import run_cleanup
from app.storage import local
from app.storage.snapshots import snapshot_usage

router = APIRouter(prefix="/storage", tags=["Storage (Admin)"])


class RetentionSettings(BaseModel):
    upload_expire_days: int
    snapshot_retention_days: int
    history_retention_days: int
    cleanup_interval_minutes: int


class StorageUsage(BaseModel):
    uploads_bytes: int
    uploads_count: int
    quota_bytes: Optional[int]          # null = tanpa batas
    quota_used_percent: Optional[float]
    snapshots_bytes: int
    snapshots_count: int
    retention: RetentionSettings


@router.get("/usage", response_model=StorageUsage)
def storage_usage(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    used = local.uploads_used_bytes(db)
    count = db.query(func.count(VideoSource.id)).filter(VideoSource.source_type == "video_upload").scalar() or 0
    quota = settings.storage_quota_mb * 1024 * 1024 or None
    snap_bytes, snap_count = snapshot_usage()
    return StorageUsage(
        uploads_bytes=used, uploads_count=count, quota_bytes=quota,
        quota_used_percent=round(used / quota * 100, 1) if quota else None,
        snapshots_bytes=snap_bytes, snapshots_count=snap_count,
        retention=RetentionSettings(
            upload_expire_days=settings.upload_expire_days,
            snapshot_retention_days=settings.snapshot_retention_days,
            history_retention_days=settings.history_retention_days,
            cleanup_interval_minutes=settings.cleanup_interval_minutes,
        ),
    )


@router.post("/cleanup")
def run_cleanup_now(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Jalankan pembersihan sekarang (sama dengan yang berjalan terjadwal). Return jumlah yang dihapus."""
    summary = run_cleanup(db)
    log_activity(db, admin.id, "storage.cleanup", None, None,
                 ", ".join(f"{k}={v}" for k, v in summary.items() if v) or "tidak ada yang dihapus")
    db.commit()
    return summary