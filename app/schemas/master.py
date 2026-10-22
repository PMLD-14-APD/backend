import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Location ----------
class LocationCreate(_In):
    name: str = Field(min_length=1, max_length=100)
    address: Optional[str] = Field(default=None, max_length=255)


class LocationUpdate(_In):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    address: Optional[str] = Field(default=None, max_length=255)


class LocationOut(_Out):
    id: uuid.UUID
    name: str
    address: Optional[str] = None


# ---------- Environment ----------
class EnvironmentCreate(_In):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)


class EnvironmentUpdate(_In):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)


class EnvironmentOut(_Out):
    id: uuid.UUID
    name: str
    description: Optional[str] = None


# ---------- APD class ----------
class ApdClassCreate(_In):
    name: str = Field(min_length=1, max_length=100)
    label_key: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)


class ApdClassUpdate(_In):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    label_key: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)


class ApdClassOut(_Out):
    id: uuid.UUID
    name: str
    label_key: str
    description: Optional[str] = None


# ---------- Environment <-> APD class ----------
class EnvironmentApdSet(_In):
    is_mandatory: bool = True


class EnvironmentApdOut(_Out):
    id: uuid.UUID
    environment_id: uuid.UUID
    apd_class_id: uuid.UUID
    is_mandatory: bool
    apd_class: ApdClassOut


# ---------- AI model ----------
class AIModelCreate(_In):
    environment_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    weights_path: str = Field(min_length=1, max_length=500)
    is_active: bool = True


class AIModelUpdate(_In):
    environment_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    version: Optional[str] = Field(default=None, min_length=1, max_length=50)
    weights_path: Optional[str] = Field(default=None, min_length=1, max_length=500)
    is_active: Optional[bool] = None


class AIModelOut(_Out):
    """Dilihat semua user (dipakai buat pilih model). Path internal tidak ditampilkan."""
    id: uuid.UUID
    environment_id: uuid.UUID
    name: str
    version: str
    is_active: bool
    created_at: Optional[datetime] = None


class AIModelAdminOut(AIModelOut):
    weights_path: str
