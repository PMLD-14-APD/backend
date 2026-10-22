import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceStatus = Literal["active", "inactive", "maintenance", "uploaded"]
SourceType = Literal["cctv_stream", "video_upload"]


class StreamSourceCreate(BaseModel):
    """Daftarkan sumber CCTV. File video dibuat lewat endpoint /upload."""
    name: str = Field(min_length=1)
    stream_url: str = Field(min_length=1)
    environment_id: uuid.UUID
    location_id: Optional[uuid.UUID] = None
    target_fps: int = Field(default=5, ge=1, le=30)
    status: Literal["active", "inactive", "maintenance"] = "inactive"


class VideoSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    location_id: Optional[uuid.UUID] = None
    target_fps: Optional[int] = Field(default=None, ge=1, le=30)
    status: Optional[Literal["active", "inactive", "maintenance"]] = None


class VideoSourceOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    location_id: Optional[uuid.UUID]
    environment_id: uuid.UUID
    name: str
    source_type: SourceType
    stream_url: Optional[str]
    file_path: Optional[str]
    file_size: Optional[int]
    duration_seconds: Optional[float]
    target_fps: int
    status: SourceStatus
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
