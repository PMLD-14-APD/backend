from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.auth import UserRegister

UserStatus = Literal["pending", "active", "rejected", "inactive", "deleted"]
UserRole = Literal["admin", "user"]


class UserCreate(UserRegister):
    """Dipakai admin buat bikin user langsung (langsung aktif)."""
    role: UserRole = "user"


class RejectRequest(BaseModel):
    reason: Optional[str] = None