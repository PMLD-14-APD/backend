import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.analysis import ComplianceStatus, SessionStatus


class SessionHistoryItem(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    source_type: str                       # cctv_stream | video_upload
    location_id: Optional[uuid.UUID]
    location_name: Optional[str]
    model_id: uuid.UUID
    user_id: Optional[uuid.UUID]
    status: SessionStatus
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_seconds: Optional[float]      # null kalau belum mulai atau masih berjalan
    total_persons: int
    total_violations: int
    compliance_rate: Optional[float]
    error_message: Optional[str]
    created_at: datetime


class SessionHistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SessionHistoryItem]


class ViolationApdItem(BaseModel):
    apd_class_id: uuid.UUID
    apd_name: str
    label_key: str
    is_present: bool
    confidence: float


class ViolationHistoryItem(BaseModel):
    id: int
    session_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    source_type: str
    location_id: Optional[uuid.UUID]
    location_name: Optional[str]
    track_id: Optional[int]
    compliance_status: ComplianceStatus
    violation_type: str                    # nilai mentah, misal NO_HELMET,NO_VEST
    violation_label: str                   # untuk tabel: "Tanpa Helm, Tanpa Rompi"
    confidence: float
    frame_number: int
    video_timestamp: float
    bbox: Any
    image_url: Optional[str]
    detected_at: datetime
    items: list[ViolationApdItem]


class ViolationHistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ViolationHistoryItem]