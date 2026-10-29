from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import UserRegister

UserStatus = Literal["pending", "active", "rejected", "inactive", "deleted"]
UserRole = Literal["admin", "user"]


class UserCreate(UserRegister):
    """Dipakai admin buat bikin user langsung (langsung aktif)."""
    role: UserRole = "user"


class UserUpdate(BaseModel):
    """Edit user oleh admin. Hanya field yang dikirim yang diubah; tidak ada yang boleh null."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    username: Optional[str] = Field(default=None, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    role: Optional[UserRole] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)  # reset password

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Nama tidak boleh kosong")
        return v

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().lower() if v is not None else v


class RejectRequest(BaseModel):
    reason: Optional[str] = None