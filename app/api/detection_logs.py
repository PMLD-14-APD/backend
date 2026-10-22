import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.analysis import AnalysisSession, DetectionLog
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.analysis import ComplianceStatus, DetectionLogOut

router = APIRouter(prefix="/detection-logs", tags=["Detection Logs"])


def _scoped(db: Session, user: User):
    q = db.query(DetectionLog).options(joinedload(DetectionLog.items))
    if user.role != "admin":
        q = (
            q.join(AnalysisSession, DetectionLog.session_id == AnalysisSession.id)
            .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
            .filter(VideoSource.user_id == user.id)
        )
    return q


@router.get("/", response_model=list[DetectionLogOut])
def list_detection_logs(
    session_id: Optional[uuid.UUID] = None,
    compliance_status: Optional[ComplianceStatus] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = _scoped(db, current_user)
    if session_id:
        q = q.filter(DetectionLog.session_id == session_id)
    if compliance_status:
        q = q.filter(DetectionLog.compliance_status == compliance_status)
    return q.order_by(DetectionLog.detected_at.desc(), DetectionLog.id.desc()).offset(offset).limit(limit).all()


@router.get("/{log_id}", response_model=DetectionLogOut)
def get_detection_log(log_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    log = _scoped(db, current_user).filter(DetectionLog.id == log_id).first()
    if log is None:
        raise HTTPException(status_code=404, detail="Log deteksi tidak ditemukan")
    return log
