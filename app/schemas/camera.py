import uuid
from datetime import datetime
from pydantic import BaseModel


class CameraCreate(BaseModel):
    name: str
    stream_url: str
    environment_id: uuid.UUID
    location_id: uuid.UUID | None = None
    target_fps: int = 5
    status: str = "inactive"


class CameraOut(BaseModel):
    id: uuid.UUID
    name: str
    stream_url: str
    environment_id: uuid.UUID
    location_id: uuid.UUID | None
    status: str
    target_fps: int
    created_at: datetime

    class Config:
        from_attributes = True
