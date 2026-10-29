"""Endpoint dashboard: hanya MEMBACA & merangkum data di database (statistik, pelanggaran, sesi).
Metrik kualitas model (akurasi, mAP, latensi) bukan urusan BE, itu wilayah AI Ops.

Hak akses: admin melihat semua data, user biasa hanya data dari sumber video miliknya."""
import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal_column
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.ai_model import ApdClass
from app.models.analysis import AnalysisSession, ComplianceStat, DetectionLog, DetectionLogItem
from app.models.environment import Environment, Location
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.dashboard import (
    ActiveSession, BreakdownOut, CountItem, DetectionTotals, GroupRow, MissingApdItem, Period,
    RecentViolation, SessionCounts, SourceCounts, SummaryOut, TrendOut, TrendPoint,
    ViolationBreakdownOut,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

MAX_RANGE_DAYS = 366
MAX_HOURLY_RANGE_DAYS = 14


# ---------------------------------------------------------------- filter & scoping
class DashboardFilters:
    def __init__(self, date_from, date_to, location_id, environment_id, source_id):
        tz = ZoneInfo(settings.dashboard_timezone)
        self.tz_name = settings.dashboard_timezone
        self.date_to = date_to or datetime.now(tz).date()
        self.date_from = date_from or (self.date_to - timedelta(days=6))   # default 7 hari terakhir
        if self.date_from > self.date_to:
            raise HTTPException(status_code=422, detail="date_from tidak boleh setelah date_to")
        if (self.date_to - self.date_from).days > MAX_RANGE_DAYS:
            raise HTTPException(status_code=422, detail=f"Rentang maksimal {MAX_RANGE_DAYS} hari")
        # [start, end) dalam zona waktu lokal; tanggal date_to ikut dihitung penuh
        self.start = datetime.combine(self.date_from, time.min, tzinfo=tz)
        self.end = datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=tz)
        self.location_id = location_id
        self.environment_id = environment_id
        self.source_id = source_id

    @property
    def period(self) -> Period:
        return Period(date_from=self.date_from, date_to=self.date_to, timezone=self.tz_name)


def get_filters(
    date_from: Optional[date] = Query(None, description="Awal periode (default: 6 hari sebelum date_to)"),
    date_to: Optional[date] = Query(None, description="Akhir periode, ikut dihitung (default: hari ini)"),
    location_id: Optional[uuid.UUID] = None,
    environment_id: Optional[uuid.UUID] = None,
    source_id: Optional[uuid.UUID] = None,
) -> DashboardFilters:
    return DashboardFilters(date_from, date_to, location_id, environment_id, source_id)


def source_conditions(f: DashboardFilters, user: User) -> list:
    conds = []
    if user.role != "admin":
        conds.append(VideoSource.user_id == user.id)
    if f.location_id:
        conds.append(VideoSource.location_id == f.location_id)
    if f.environment_id:
        conds.append(VideoSource.environment_id == f.environment_id)
    if f.source_id:
        conds.append(VideoSource.id == f.source_id)
    return conds


def stats_query(db: Session, f: DashboardFilters, user: User, *cols):
    return (
        db.query(*cols).select_from(ComplianceStat)
        .join(AnalysisSession, ComplianceStat.session_id == AnalysisSession.id)
        .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
        .filter(ComplianceStat.bucket_start >= f.start, ComplianceStat.bucket_start < f.end,
                *source_conditions(f, user))
    )


def logs_query(db: Session, f: DashboardFilters, user: User, *cols):
    return (
        db.query(*cols).select_from(DetectionLog)
        .join(AnalysisSession, DetectionLog.session_id == AnalysisSession.id)
        .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
        .filter(DetectionLog.detected_at >= f.start, DetectionLog.detected_at < f.end,
                *source_conditions(f, user))
    )


def _stat_sums():
    S = ComplianceStat
    return (
        func.coalesce(func.sum(S.total_persons), 0),
        func.coalesce(func.sum(S.lengkap), 0),
        func.coalesce(func.sum(S.kurang_lengkap), 0),
        func.coalesce(func.sum(S.tidak_digunakan), 0),
    )


def rate(lengkap: int, total: int) -> Optional[float]:
    """Persentase kepatuhan = orang dengan APD lengkap / total orang."""
    return round(lengkap / total * 100, 2) if total else None


# ---------------------------------------------------------------- endpoint
@router.get("/summary", response_model=SummaryOut)
def summary(f: DashboardFilters = Depends(get_filters), db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Kartu ringkasan: sumber video, sesi, total orang, pelanggaran, dan tingkat kepatuhan."""
    persons, lengkap, kurang, tidak = (int(v) for v in stats_query(db, f, user, *_stat_sums()).one())
    violations = logs_query(db, f, user, func.count(DetectionLog.id)).scalar() or 0

    src_rows = (
        db.query(VideoSource.source_type, VideoSource.status, func.count(VideoSource.id))
        .filter(*source_conditions(f, user)).group_by(VideoSource.source_type, VideoSource.status).all()
    )
    by_type: dict[str, int] = {}
    cctv_active = 0
    for stype, status, n in src_rows:
        by_type[stype] = by_type.get(stype, 0) + n
        if stype == "cctv_stream" and status == "active":
            cctv_active += n

    ses_q = (
        db.query(AnalysisSession.status, func.count(AnalysisSession.id))
        .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
        .filter(*source_conditions(f, user))
    )
    in_period = dict(
        ses_q.filter(AnalysisSession.created_at >= f.start, AnalysisSession.created_at < f.end)
        .group_by(AnalysisSession.status).all()
    )
    processing_now = dict(ses_q.group_by(AnalysisSession.status).all()).get("processing", 0)

    pending = None
    if user.role == "admin":
        pending = db.query(func.count(User.id)).filter(User.status == "pending").scalar() or 0

    return SummaryOut(
        period=f.period,
        sources=SourceCounts(total=sum(by_type.values()), cctv_stream=by_type.get("cctv_stream", 0),
                             video_upload=by_type.get("video_upload", 0), cctv_active=cctv_active),
        sessions=SessionCounts(total=sum(in_period.values()), queued=in_period.get("queued", 0),
                               processing=in_period.get("processing", 0), done=in_period.get("done", 0),
                               failed=in_period.get("failed", 0), processing_now=processing_now),
        detection=DetectionTotals(total_persons=persons, lengkap=lengkap, kurang_lengkap=kurang,
                                  tidak_digunakan=tidak, total_violations=violations,
                                  compliance_rate=rate(lengkap, persons)),
        pending_users=pending,
    )


@router.get("/trend", response_model=TrendOut)
def trend(interval: Literal["hour", "day", "week", "month"] = "day",
          f: DashboardFilters = Depends(get_filters), db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    """Grafik tren kepatuhan. Hanya periode yang punya data yang muncul (tidak ada pengisian nol)."""
    if interval == "hour" and (f.date_to - f.date_from).days > MAX_HOURLY_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"interval=hour maksimal {MAX_HOURLY_RANGE_DAYS} hari")
    # literal (bukan bind param) supaya SELECT dan GROUP BY identik di PostgreSQL;
    # aman karena tz sudah divalidasi ZoneInfo dan interval dibatasi Literal.
    tz_lit = literal_column("'" + f.tz_name.replace("'", "''") + "'")
    bucket = func.date_trunc(literal_column(f"'{interval}'"), func.timezone(tz_lit, ComplianceStat.bucket_start))
    rows = stats_query(db, f, user, bucket, *_stat_sums()).group_by(bucket).order_by(bucket).all()
    points = [
        TrendPoint(bucket=b.isoformat(), total_persons=int(p), lengkap=int(l), kurang_lengkap=int(k),
                   tidak_digunakan=int(t), compliance_rate=rate(int(l), int(p)))
        for b, p, l, k, t in rows
    ]
    return TrendOut(period=f.period, interval=interval, points=points)


@router.get("/violations", response_model=ViolationBreakdownOut)
def violation_breakdown(f: DashboardFilters = Depends(get_filters), db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Pelanggaran per status (kurang_lengkap / tidak_digunakan) dan per APD yang tidak terpakai."""
    status_rows = (
        logs_query(db, f, user, DetectionLog.compliance_status, func.count(DetectionLog.id))
        .group_by(DetectionLog.compliance_status).order_by(func.count(DetectionLog.id).desc()).all()
    )
    apd_rows = (
        logs_query(db, f, user, ApdClass.id, ApdClass.label_key, ApdClass.name, func.count(DetectionLogItem.id))
        .join(DetectionLogItem, DetectionLogItem.detection_log_id == DetectionLog.id)
        .join(ApdClass, DetectionLogItem.apd_class_id == ApdClass.id)
        .filter(DetectionLogItem.is_present.is_(False))
        .group_by(ApdClass.id, ApdClass.label_key, ApdClass.name)
        .order_by(func.count(DetectionLogItem.id).desc()).all()
    )
    return ViolationBreakdownOut(
        period=f.period,
        total_violations=sum(n for _, n in status_rows),
        by_status=[CountItem(key=k, count=n) for k, n in status_rows],
        by_missing_apd=[MissingApdItem(apd_class_id=i, label_key=lk, name=nm, count=n)
                        for i, lk, nm, n in apd_rows],
    )


@router.get("/breakdown", response_model=BreakdownOut)
def breakdown(group_by: Literal["source", "location", "environment"] = "location",
              f: DashboardFilters = Depends(get_filters), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Perbandingan kepatuhan & pelanggaran per sumber video / lokasi / environment."""
    if group_by == "source":
        gid, gname, join = VideoSource.id, VideoSource.name, None
    elif group_by == "location":
        gid, gname = Location.id, func.coalesce(Location.name, "Tanpa lokasi")
        join = lambda q: q.outerjoin(Location, VideoSource.location_id == Location.id)
    else:
        gid, gname = Environment.id, Environment.name
        join = lambda q: q.join(Environment, VideoSource.environment_id == Environment.id)

    sq = stats_query(db, f, user, gid, gname, *_stat_sums())
    lq = logs_query(db, f, user, gid, gname, func.count(DetectionLog.id))
    if join:
        sq, lq = join(sq), join(lq)
    stat_rows = sq.group_by(gid, gname).all()
    log_rows = lq.group_by(gid, gname).all()

    merged: dict = {}
    for i, name, p, l, k, t in stat_rows:
        merged[i] = dict(name=name, p=int(p), l=int(l), k=int(k), t=int(t), v=0)
    for i, name, n in log_rows:
        merged.setdefault(i, dict(name=name, p=0, l=0, k=0, t=0, v=0))["v"] = n
    rows = [
        GroupRow(id=i, name=d["name"], total_persons=d["p"], lengkap=d["l"], kurang_lengkap=d["k"],
                 tidak_digunakan=d["t"], compliance_rate=rate(d["l"], d["p"]), total_violations=d["v"])
        for i, d in merged.items()
    ]
    rows.sort(key=lambda r: (-r.total_violations, r.name))
    return BreakdownOut(period=f.period, group_by=group_by, rows=rows)


@router.get("/recent-violations", response_model=list[RecentViolation])
def recent_violations(limit: int = Query(default=10, ge=1, le=50),
                      f: DashboardFilters = Depends(get_filters), db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Pelanggaran terbaru beserta nama sumber, lokasi, dan foto bukti."""
    rows = (
        logs_query(db, f, user, DetectionLog, VideoSource.id, VideoSource.name, Location.name)
        .outerjoin(Location, VideoSource.location_id == Location.id)
        .order_by(DetectionLog.detected_at.desc(), DetectionLog.id.desc()).limit(limit).all()
    )
    return [
        RecentViolation(id=d.id, session_id=d.session_id, source_id=sid, source_name=sname,
                        location_name=lname, track_id=d.track_id, compliance_status=d.compliance_status,
                        violation_type=d.violation_type, confidence=d.confidence, image_url=d.image_url,
                        detected_at=d.detected_at)
        for d, sid, sname, lname in rows
    ]


@router.get("/active-sessions", response_model=list[ActiveSession])
def active_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Sesi analisis yang sedang berjalan sekarang (tidak terikat periode)."""
    q = (
        db.query(AnalysisSession, VideoSource, Location.name)
        .join(VideoSource, AnalysisSession.source_id == VideoSource.id)
        .outerjoin(Location, VideoSource.location_id == Location.id)
        .filter(AnalysisSession.status == "processing")
    )
    if user.role != "admin":
        q = q.filter(VideoSource.user_id == user.id)
    rows = q.order_by(AnalysisSession.started_at.desc()).all()
    counts = {}
    if rows:
        ids = [s.id for s, _, _ in rows]
        counts = dict(
            db.query(DetectionLog.session_id, func.count(DetectionLog.id))
            .filter(DetectionLog.session_id.in_(ids)).group_by(DetectionLog.session_id).all()
        )
    return [
        ActiveSession(id=s.id, source_id=src.id, source_name=src.name, source_type=src.source_type,
                      location_name=lname, started_at=s.started_at, violations_so_far=counts.get(s.id, 0))
        for s, src, lname in rows
    ]