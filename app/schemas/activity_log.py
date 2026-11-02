import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ActivityLogItem(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]          # null kalau pelakunya sudah dihapus permanen
    user_name: Optional[str]
    username: Optional[str]
    action: str                           # user.approve, source.upload, auth.logout, ...
    target_type: Optional[str]
    target_id: Optional[uuid.UUID]
    detail: Optional[str]
    created_at: datetime


class ActivityLogPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ActivityLogItem]