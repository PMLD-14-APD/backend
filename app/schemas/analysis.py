import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

SessionStatus = Literal["queued", "processing", "done", "failed"]
ComplianceStatus = Literal["kurang_lengkap", "tidak_digunakan"]


class SessionCreate(BaseModel):
    source_id: uuid.UUID
    # kosong = pakai model aktif terbaru milik environment sumber video
    model_id: Optional[uuid.UUID] = None


class SessionOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    model_id: uuid.UUID
    user_id: Optional[uuid.UUID]
    status: SessionStatus
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    total_persons: int
    total_violations: int
    compliance_rate: Optional[float]
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ComplianceStatOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    bucket_start: datetime
    total_persons: int
    lengkap: int
    kurang_lengkap: int
    tidak_digunakan: int

    class Config:
        from_attributes = True


class DetectionLogItemOut(BaseModel):
    id: int
    apd_class_id: uuid.UUID
    is_present: bool
    confidence: float

    class Config:
        from_attributes = True


class DetectionLogOut(BaseModel):
    id: int
    session_id: uuid.UUID
    track_id: Optional[int]
    compliance_status: ComplianceStatus
    violation_type: str
    confidence: float
    frame_number: int
    video_timestamp: float
    bbox: Any
    image_url: Optional[str]
    detected_at: datetime
    items: list[DetectionLogItemOut] = []

    class Config:
        from_attributes = True
