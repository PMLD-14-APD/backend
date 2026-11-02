import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.auth import UserOut, UserRegister

UserStatus = Literal["pending", "active", "rejected", "inactive", "deleted"]
UserRole = Literal["admin", "user"]


class UserCreate(UserRegister):
    """Dipakai admin buat bikin user langsung (langsung aktif)."""
    role: UserRole = "user"
    confirm_password: str = Field(max_length=72)

    @model_validator(mode="after")
    def password_harus_sama(self):
        if self.password != self.confirm_password:
            raise ValueError("Konfirmasi password tidak sama dengan password")
        return self


class UserUpdate(BaseModel):
    """Semua field opsional: hanya field yang dikirim yang diubah.
    Kirim `password` + `confirm_password` untuk reset password."""
    name: Optional[str] = Field(default=None, max_length=100)
    username: Optional[str] = Field(default=None, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    role: Optional[UserRole] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)  # 72 = batas bcrypt
    confirm_password: Optional[str] = Field(default=None, max_length=72)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Nama tidak boleh kosong")
        return v

    @model_validator(mode="after")
    def validasi_kombinasi(self):
        # field yang tidak boleh null kalau dikirim
        for field in ("name", "username", "role"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} tidak boleh null")
        if self.password is not None and self.password != self.confirm_password:
            raise ValueError("Konfirmasi password tidak sama dengan password")
        if self.password is None and self.confirm_password is not None:
            raise ValueError("Isi password baru juga, atau kosongkan confirm_password")
        return self


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class UserPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[UserOut]