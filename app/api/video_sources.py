import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import log_activity
from app.models.analysis import AnalysisSession
from app.models.environment import Environment, Location
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.video_source import StreamSourceCreate, VideoSourceOut, VideoSourceUpdate
from app.services.inference.manager import inference_manager
from app.services.stream_manager import stream_manager
from app.storage import local

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


@router.get("/", response_model=list[VideoSourceOut])
def list_sources(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(VideoSource)
    if current_user.role != "admin":
        q = q.filter(VideoSource.user_id == current_user.id)
    return q.order_by(VideoSource.created_at.desc()).all()


@router.get("/{source_id}", response_model=VideoSourceOut)
def get_source(source_id: uuid.UUID, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    return get_source_for_user(db, source_id, current_user)


@router.post("/", response_model=VideoSourceOut, status_code=201)
def register_stream(payload: StreamSourceCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """Daftarkan sumber CCTV (stream RTSP/HTTP)."""
    _check_refs(db, payload.environment_id, payload.location_id)
    src = VideoSource(**payload.model_dump(), user_id=current_user.id, source_type="cctv_stream")
    db.add(src)
    db.flush()
    log_activity(db, current_user.id, "source.create", "video_source", src.id, src.name)
    db.commit()
    db.refresh(src)
    return src


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
    return src


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
    return src


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
    log_activity(db, current_user.id, "source.delete", "video_source", src.id, name)
    db.delete(src)
    db.commit()
    local.delete_file(file_path)
    return {"message": f"Sumber video '{name}' dihapus"}
