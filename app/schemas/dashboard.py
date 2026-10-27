import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class Period(BaseModel):
    date_from: date
    date_to: date
    timezone: str


class SourceCounts(BaseModel):
    total: int
    cctv_stream: int
    video_upload: int
    cctv_active: int


class SessionCounts(BaseModel):
    total: int            # sesi yang dibuat dalam periode
    queued: int
    processing: int
    done: int
    failed: int
    processing_now: int   # sedang berjalan sekarang (tidak terikat periode)


class DetectionTotals(BaseModel):
    total_persons: int
    lengkap: int
    kurang_lengkap: int
    tidak_digunakan: int
    total_violations: int
    compliance_rate: Optional[float]   # persen 0-100, null kalau belum ada orang terdeteksi


class SummaryOut(BaseModel):
    period: Period
    sources: SourceCounts
    sessions: SessionCounts
    detection: DetectionTotals
    pending_users: Optional[int] = None   # hanya diisi untuk admin


class TrendPoint(BaseModel):
    bucket: str                 # awal periode, waktu lokal (ISO 8601)
    total_persons: int
    lengkap: int
    kurang_lengkap: int
    tidak_digunakan: int
    compliance_rate: Optional[float]


class TrendOut(BaseModel):
    period: Period
    interval: str
    points: list[TrendPoint]


class CountItem(BaseModel):
    key: str
    count: int


class MissingApdItem(BaseModel):
    apd_class_id: uuid.UUID
    label_key: str
    name: str
    count: int          # jumlah pelanggaran yang APD ini tidak terpakai


class ViolationBreakdownOut(BaseModel):
    period: Period
    total_violations: int
    by_status: list[CountItem]
    by_missing_apd: list[MissingApdItem]


class GroupRow(BaseModel):
    id: Optional[uuid.UUID]     # null = "Tanpa lokasi"
    name: str
    total_persons: int
    lengkap: int
    kurang_lengkap: int
    tidak_digunakan: int
    compliance_rate: Optional[float]
    total_violations: int


class BreakdownOut(BaseModel):
    period: Period
    group_by: str
    rows: list[GroupRow]


class RecentViolation(BaseModel):
    id: int
    session_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    location_name: Optional[str]
    track_id: Optional[int]
    compliance_status: str
    violation_type: str
    confidence: float
    image_url: Optional[str]
    detected_at: datetime


class ActiveSession(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    source_type: str
    location_name: Optional[str]
    started_at: Optional[datetime]
    violations_so_far: int