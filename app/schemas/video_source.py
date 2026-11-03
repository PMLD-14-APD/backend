import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.stream_url import mask_stream_url, validate_stream_url

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

    @field_validator("stream_url")
    @classmethod
    def cek_stream_url(cls, v: str) -> str:
        return validate_stream_url(v)   # ValueError -> 422


class VideoSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    location_id: Optional[uuid.UUID] = None
    target_fps: Optional[int] = Field(default=None, ge=1, le=30)
    status: Optional[Literal["active", "inactive", "maintenance"]] = None


class VideoSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    location_id: Optional[uuid.UUID]
    location_name: Optional[str] = None
    environment_id: uuid.UUID
    name: str
    source_type: SourceType
    stream_url: Optional[str]             # password selalu disamarkan; URL asli hanya ada di database
    file_size: Optional[int]
    duration_seconds: Optional[float]
    target_fps: int
    status: SourceStatus
    is_live: bool = False                 # CCTV yang sedang dianalisis (ada sesi 'processing')
    active_session_id: Optional[uuid.UUID] = None   # sesi 'processing' terbaru, kalau ada
    expires_at: Optional[datetime]
    created_at: datetime

    @field_validator("stream_url")
    @classmethod
    def samarkan_stream_url(cls, v: Optional[str]) -> Optional[str]:
        return mask_stream_url(v)


class VideoSourcePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[VideoSourceOut]