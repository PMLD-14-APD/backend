import uuid
from datetime import datetime
from pydantic import BaseModel


class DetectionLogOut(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    model_id: uuid.UUID
    apd_class_id: uuid.UUID
    violation_type: str
    confidence: float
    image_url: str | None
    detected_at: datetime

    class Config:
        from_attributes = True
