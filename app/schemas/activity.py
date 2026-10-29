import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ActivityLogOut(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]        # null kalau pelakunya dihapus permanen
    username: Optional[str]
    user_name: Optional[str]
    action: str                         # user.create, source.upload, ...
    target_type: Optional[str]
    target_id: Optional[uuid.UUID]
    detail: Optional[str]
    created_at: Optional[datetime]