import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.detection_log import DetectionLog
from app.schemas.detection_log import DetectionLogOut

router = APIRouter()


@router.get("/", response_model=list[DetectionLogOut])
def list_detection_logs(
    camera_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(DetectionLog)
    if camera_id:
        query = query.filter(DetectionLog.camera_id == camera_id)
    return query.order_by(DetectionLog.detected_at.desc()).limit(limit).all()
