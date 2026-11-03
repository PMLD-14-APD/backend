import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserRegister(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)  # 72 = batas bcrypt

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    username: str
    role: str
    status: str
    approved_by: Optional[uuid.UUID] = None
    approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None      # detik sampai token kedaluwarsa; frontend memanggil /auth/refresh sebelum itu


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)   # 72 = batas bcrypt
    confirm_password: str = Field(max_length=72)

    @model_validator(mode="after")
    def validasi(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Konfirmasi password tidak sama dengan password baru")
        if self.new_password == self.current_password:
            raise ValueError("Password baru harus berbeda dari password lama")
        return self