import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import log_activity
from app.models.analysis import AnalysisSession
from app.models.environment import Environment, Location
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.video_source import (
    SourceStatus, SourceType, StreamSourceCreate, VideoSourceOut, VideoSourcePage, VideoSourceUpdate,
)
from app.services.history import escape_like
from app.services.inference.manager import inference_manager
from app.services.stream_manager import stream_manager
from app.services.stream_probe import probe_stream
from app.storage import local
from app.storage.snapshots import delete_session_snapshots

router = APIRouter(prefix="/video-sources", tags=["Video Sources"])


def get_source_for_user(db: Session, source_id: uuid.UUID, user: User) -> VideoSource:
    """Admin boleh semua; user biasa hanya sumber miliknya sendiri."""
    src = db.get(VideoSource, source_id)
    if src is None or (user.role != "admin" and src.user_id != user.id):
        raise HTTPException(status_code=404, detail="Sumber video tidak ditemukan")
    return src


def _check_refs(db: Session, environment_id: uuid.UUID, location_id: Optional[uuid.UUID]) -> None:
    if db.get(Environment, environment_id) is None:
        raise HTTPException(status_code=422, detail="Environment tidak ditemukan")
    if location_id is not None and db.get(Location, location_id) is None:
        raise HTTPException(status_code=422, detail="Lokasi tidak ditemukan")


SortOrder = Literal["desc", "asc"]


def _active_session_subquery():
    """ID sesi 'processing' terbaru milik sumber (sebagai subquery berkorelasi), NULL kalau tidak ada."""
    return (
        select(AnalysisSession.id)
        .where(AnalysisSession.source_id == VideoSource.id, AnalysisSession.status == "processing")
        .order_by(AnalysisSession.created_at.desc())
        .limit(1)
        .correlate(VideoSource)
        .scalar_subquery()
    )


def _to_out(src: VideoSource, location_name: Optional[str],
            active_session_id: Optional[uuid.UUID]) -> VideoSourceOut:
    out = VideoSourceOut.model_validate(src)
    out.location_name = location_name
    out.active_session_id = active_session_id
    out.is_live = active_session_id is not None and src.source_type == "cctv_stream"
    return out


def _out_for(db: Session, src: VideoSource) -> VideoSourceOut:
    """Out untuk satu sumber (dipakai endpoint non-daftar)."""
    location_name = None
    if src.location_id is not None:
        location_name = db.query(Location.name).filter(Location.id == src.location_id).scalar()
    active = (
        db.query(AnalysisSession.id)
        .filter(AnalysisSession.source_id == src.id, AnalysisSession.status == "processing")
        .order_by(AnalysisSession.created_at.desc())
        .first()
    )
    return _to_out(src, location_name, active[0] if active else None)


@router.get("/", response_model=VideoSourcePage)
def list_sources(
    search: Optional[str] = Query(None, description="Cari nama kamera atau nama lokasi"),
    location_id: Optional[uuid.UUID] = Query(None, description="Filter satu lokasi"),
    source_type: Optional[SourceType] = None,
    status: Optional[SourceStatus] = None,
    live: Optional[bool] = Query(None, description="true: hanya CCTV yang sedang dianalisis; false: sisanya"),
    sort_order: SortOrder = "desc",
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Daftar kamera/sumber video untuk halaman Monitoring. Admin melihat semua, user biasa hanya miliknya."""
    active_sq = _active_session_subquery()
    q = (
        db.query(VideoSource, Location.name, active_sq.label("active_session_id"))
        .outerjoin(Location, VideoSource.location_id == Location.id)
    )
    if current_user.role != "admin":
        q = q.filter(VideoSource.user_id == current_user.id)
    if search and search.strip():
        like = f"%{escape_like(search.strip())}%"
        q = q.filter(VideoSource.name.ilike(like, escape="\\") | Location.name.ilike(like, escape="\\"))
    if location_id:
        q = q.filter(VideoSource.location_id == location_id)
    if source_type:
        q = q.filter(VideoSource.source_type == source_type)
    if status:
        q = q.filter(VideoSource.status == status)
    if live is not None:
        is_live = and_(VideoSource.source_type == "cctv_stream", active_sq.is_not(None))
        q = q.filter(is_live if live else ~is_live)

    total = q.count()
    if sort_order == "desc":
        q = q.order_by(VideoSource.created_at.desc(), VideoSource.id.desc())
    else:
        q = q.order_by(VideoSource.created_at.asc(), VideoSource.id.asc())
    rows = q.offset(offset).limit(limit).all()
    items = [_to_out(src, loc_name, active_id) for src, loc_name, active_id in rows]
    return VideoSourcePage(total=total, limit=limit, offset=offset, items=items)


@router.get("/{source_id}", response_model=VideoSourceOut)
def get_source(source_id: uuid.UUID, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    return _out_for(db, get_source_for_user(db, source_id, current_user))


@router.post("/", response_model=VideoSourceOut, status_code=201)
def register_stream(payload: StreamSourceCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """Daftarkan sumber CCTV (stream RTSP/HTTP). Koneksi diuji dulu sebelum disimpan."""
    if settings.cctv_register_admin_only and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Pendaftaran CCTV hanya bisa dilakukan admin")
    _check_refs(db, payload.environment_id, payload.location_id)

    if settings.validate_stream_on_create:
        ok, reason = probe_stream(payload.stream_url, settings.stream_probe_timeout_seconds)
        if not ok:
            raise HTTPException(status_code=422, detail=f"Tidak dapat terhubung ke stream: {reason}")

    src = VideoSource(**payload.model_dump(), user_id=current_user.id, source_type="cctv_stream")
    db.add(src)
    db.flush()
    log_activity(db, current_user.id, "source.create", "video_source", src.id, src.name)
    db.commit()
    db.refresh(src)
    return _out_for(db, src)


@router.post("/upload", response_model=VideoSourceOut, status_code=201)
def upload_video(
    name: str = Form(..., min_length=1),
    environment_id: uuid.UUID = Form(...),
    location_id: Optional[uuid.UUID] = Form(None),
    target_fps: int = Form(5, ge=1, le=30),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unggah file video. Otomatis kedaluwarsa setelah UPLOAD_EXPIRE_DAYS hari (default 30)."""
    _check_refs(db, environment_id, location_id)

    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if file.filename and "." in file.filename else ""
    if ext not in local.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422,
                            detail=f"Format tidak didukung. Gunakan: {', '.join(sorted(local.ALLOWED_EXTENSIONS))}")

    quota_bytes = settings.storage_quota_mb * 1024 * 1024      # 0 = tanpa batas
    used_bytes = local.uploads_used_bytes(db) if quota_bytes else 0
    if quota_bytes and used_bytes >= quota_bytes:
        raise HTTPException(status_code=507, detail="Penyimpanan video penuh. Hapus video lama atau hubungi admin")

    path = local.new_upload_path(file.filename)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413,
                                        detail=f"File melebihi batas {settings.max_upload_mb} MB")
                if quota_bytes and used_bytes + size > quota_bytes:
                    raise HTTPException(status_code=507,
                                        detail="Penyimpanan video penuh. Hapus video lama atau hubungi admin")
                out.write(chunk)

        duration, _fps = local.probe_video(path)
        if duration is None:
            raise HTTPException(status_code=422, detail="File bukan video yang valid")

        now = datetime.now(timezone.utc)
        src = VideoSource(
            user_id=current_user.id,
            location_id=location_id,
            environment_id=environment_id,
            name=name,
            source_type="video_upload",
            file_path=str(path),
            file_size=size,
            duration_seconds=duration,
            target_fps=target_fps,
            status="uploaded",
            expires_at=now + timedelta(days=settings.upload_expire_days),
        )
        db.add(src)
        db.flush()
        log_activity(db, current_user.id, "source.upload", "video_source", src.id, name)
        db.commit()
    except Exception:
        db.rollback()
        local.delete_file(str(path))   # jangan tinggalkan file yatim
        raise
    db.refresh(src)
    return _out_for(db, src)


@router.patch("/{source_id}", response_model=VideoSourceOut)
def update_source(source_id: uuid.UUID, payload: VideoSourceUpdate, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    src = get_source_for_user(db, source_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and src.source_type == "video_upload":
        raise HTTPException(status_code=422, detail="Status sumber unggahan tidak bisa diubah")
    if "location_id" in data:
        _check_refs(db, src.environment_id, data["location_id"])
    for key in ("name", "target_fps", "status"):
        if key in data and data[key] is None:
            raise HTTPException(status_code=422, detail=f"Field '{key}' tidak boleh null")
    for key, value in data.items():
        setattr(src, key, value)
    log_activity(db, current_user.id, "source.update", "video_source", src.id, src.name)
    db.commit()
    db.refresh(src)
    return _out_for(db, src)


@router.delete("/{source_id}")
def delete_source(source_id: uuid.UUID, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    """Hapus sumber. Sesi analisis, statistik, dan log deteksinya ikut terhapus (CASCADE)."""
    src = get_source_for_user(db, source_id, current_user)
    running = db.query(AnalysisSession).filter(
        AnalysisSession.source_id == src.id, AnalysisSession.status == "processing"
    ).all()
    for s in running:
        inference_manager.stop(s.id)
        stream_manager.stop(str(s.id))
    file_path, name = src.file_path, src.name
    session_ids = [row.id for row in db.query(AnalysisSession.id).filter(AnalysisSession.source_id == src.id)]
    log_activity(db, current_user.id, "source.delete", "video_source", src.id, name)
    db.delete(src)
    db.commit()
    local.delete_file(file_path)
    for sid in session_ids:            # foto bukti milik sesi-sesi yang ikut terhapus
        delete_session_snapshots(sid)
    return {"message": f"Sumber video '{name}' dihapus"}