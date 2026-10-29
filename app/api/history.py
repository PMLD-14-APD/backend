"""Riwayat analisis: tabel sesi analisis dan tabel pelanggaran, dengan filter, pencarian, dan paginasi.

Endpoint operasional (/analysis-sessions dan /detection-logs) dibiarkan apa adanya;
endpoint di sini khusus untuk halaman riwayat.

Hak akses: admin melihat semua data, user biasa hanya data dari sumber video miliknya."""
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutils import day_bounds
from app.models.ai_model import ApdClass
from app.models.analysis import AnalysisSession, DetectionLog, DetectionLogItem
from app.models.environment import Location
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.analysis import ComplianceStatus, SessionStatus
from app.schemas.history import (
    SessionHistoryItem, SessionHistoryPage, ViolationApdItem, ViolationHistoryItem,
    ViolationHistoryPage,
)
from app.services.history import duration_seconds, escape_like, violation_label

router = APIRouter(prefix="/history", tags=["Riwayat Analisis"])

SourceType = Literal["cctv_stream", "video_upload"]
SortOrder = Literal["desc", "asc"]


# ---------------------------------------------------------------- filter bersama
def date_range(
    date_from: Optional[date] = Query(None, description="Tanggal awal (waktu lokal), ikut dihitung"),
    date_to: Optional[date] = Query(None, description="Tanggal akhir (waktu lokal), ikut dihitung"),
) -> tuple[Optional[datetime], Optional[datetime]]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from tidak boleh setelah date_to")
    return day_bounds(date_from, date_to)


def _scope(query, user: User):
    """Query harus sudah join VideoSource."""
    if user.role != "admin":
        query = query.filter(VideoSource.user_id == user.id)
    return query


def _search(query, search: Optional[str]):
    """Cari nama sumber atau nama lokasi (query harus sudah join VideoSource dan Location)."""
    if search and search.strip():
        like = f"%{escape_like(search.strip())}%"
        query = query.filter(VideoSource.name.ilike(like, escape="\\") | Location.name.ilike(like, escape="\\"))
    return query


# ---------------------------------------------------------------- riwayat sesi analisis
@router.get("/sessions", response_model=SessionHistoryPage)
def session_history(
    source_id: Optional[uuid.UUID] = None,
    location_id: Optional[uuid.UUID] = None,
    source_type: Optional[SourceType] = None,
    status: Optional[SessionStatus] = None,
    search: Optional[str] = Query(None, description="Cari nama sumber atau nama lokasi"),
    rng: tuple = Depends(date_range),
    sort_order: SortOrder = "desc",
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tabel riwayat analisis: sumber, lokasi, waktu mulai, durasi, jumlah pelanggaran, kepatuhan.
    Filter tanggal memakai waktu mulai sesi (sesi yang belum mulai memakai waktu dibuatnya)."""
    start, end = rng
    session_time = func.coalesce(AnalysisSession.started_at, AnalysisSession.created_at)

    query = (
        db.query(AnalysisSession, VideoSource, Location.name)
        .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
        .outerjoin(Location, VideoSource.location_id == Location.id)
    )
    query = _search(_scope(query, current_user), search)
    if source_id:
        query = query.filter(AnalysisSession.source_id == source_id)
    if location_id:
        query = query.filter(VideoSource.location_id == location_id)
    if source_type:
        query = query.filter(VideoSource.source_type == source_type)
    if status:
        query = query.filter(AnalysisSession.status == status)
    if start:
        query = query.filter(session_time >= start)
    if end:
        query = query.filter(session_time < end)

    total = query.count()
    order = session_time.desc() if sort_order == "desc" else session_time.asc()
    tie = AnalysisSession.id.desc() if sort_order == "desc" else AnalysisSession.id.asc()
    rows = query.order_by(order, tie).offset(offset).limit(limit).all()

    items = [
        SessionHistoryItem(
            id=s.id, source_id=src.id, source_name=src.name, source_type=src.source_type,
            location_id=src.location_id, location_name=loc_name, model_id=s.model_id, user_id=s.user_id,
            status=s.status, started_at=s.started_at, finished_at=s.finished_at,
            duration_seconds=duration_seconds(s.started_at, s.finished_at),
            total_persons=s.total_persons, total_violations=s.total_violations,
            compliance_rate=s.compliance_rate, error_message=s.error_message, created_at=s.created_at,
        )
        for s, src, loc_name in rows
    ]
    return SessionHistoryPage(total=total, limit=limit, offset=offset, items=items)


# ---------------------------------------------------------------- riwayat pelanggaran
def _violation_query(db: Session, user: User):
    query = (
        db.query(DetectionLog, VideoSource, Location.name)
        .join(AnalysisSession, DetectionLog.session_id == AnalysisSession.id)
        .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
        .outerjoin(Location, VideoSource.location_id == Location.id)
    )
    return _scope(query, user)


def _build_violations(db: Session, rows) -> list[ViolationHistoryItem]:
    """Rincian APD dimuat dengan satu query untuk seluruh halaman (bukan satu per baris)."""
    if not rows:
        return []
    apd = {a.id: a for a in db.query(ApdClass).all()}
    apd_names = {f"NO_{a.label_key.upper()}": a.name for a in apd.values()}
    items_by_log: dict[int, list[DetectionLogItem]] = {}
    for it in (
        db.query(DetectionLogItem)
        .filter(DetectionLogItem.detection_log_id.in_([log.id for log, _, _ in rows]))
        .order_by(DetectionLogItem.id)
        .all()
    ):
        items_by_log.setdefault(it.detection_log_id, []).append(it)

    return [
        ViolationHistoryItem(
            id=log.id, session_id=log.session_id, source_id=src.id, source_name=src.name,
            source_type=src.source_type, location_id=src.location_id, location_name=loc_name,
            track_id=log.track_id, compliance_status=log.compliance_status,
            violation_type=log.violation_type,
            violation_label=violation_label(log.violation_type, apd_names),
            confidence=log.confidence, frame_number=log.frame_number,
            video_timestamp=log.video_timestamp, bbox=log.bbox, image_url=log.image_url,
            detected_at=log.detected_at,
            items=[
                ViolationApdItem(
                    apd_class_id=it.apd_class_id, apd_name=apd[it.apd_class_id].name,
                    label_key=apd[it.apd_class_id].label_key, is_present=it.is_present,
                    confidence=it.confidence,
                )
                for it in items_by_log.get(log.id, [])
            ],
        )
        for log, src, loc_name in rows
    ]


@router.get("/violations", response_model=ViolationHistoryPage)
def violation_history(
    source_id: Optional[uuid.UUID] = None,
    location_id: Optional[uuid.UUID] = None,
    session_id: Optional[uuid.UUID] = None,
    compliance_status: Optional[ComplianceStatus] = None,
    apd_class_id: Optional[uuid.UUID] = Query(None, description="Hanya pelanggaran yang APD ini tidak terpakai"),
    search: Optional[str] = Query(None, description="Cari nama sumber atau nama lokasi"),
    rng: tuple = Depends(date_range),
    sort_order: SortOrder = "desc",
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tabel riwayat pelanggaran: waktu, kamera, lokasi, catatan pelanggaran, bukti foto."""
    start, end = rng
    query = _search(_violation_query(db, current_user), search)
    if source_id:
        query = query.filter(AnalysisSession.source_id == source_id)
    if location_id:
        query = query.filter(VideoSource.location_id == location_id)
    if session_id:
        query = query.filter(DetectionLog.session_id == session_id)
    if compliance_status:
        query = query.filter(DetectionLog.compliance_status == compliance_status)
    if apd_class_id:
        query = query.filter(DetectionLog.items.any(
            (DetectionLogItem.apd_class_id == apd_class_id) & DetectionLogItem.is_present.is_(False)
        ))
    if start:
        query = query.filter(DetectionLog.detected_at >= start)
    if end:
        query = query.filter(DetectionLog.detected_at < end)

    total = query.count()
    if sort_order == "desc":
        order = (DetectionLog.detected_at.desc(), DetectionLog.id.desc())
    else:
        order = (DetectionLog.detected_at.asc(), DetectionLog.id.asc())
    rows = query.order_by(*order).offset(offset).limit(limit).all()
    return ViolationHistoryPage(total=total, limit=limit, offset=offset, items=_build_violations(db, rows))


@router.get("/violations/{log_id}", response_model=ViolationHistoryItem)
def violation_detail(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Detail satu pelanggaran, untuk tombol 'Lihat' bukti foto."""
    rows = _violation_query(db, current_user).filter(DetectionLog.id == log_id).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Pelanggaran tidak ditemukan")
    return _build_violations(db, rows)[0]