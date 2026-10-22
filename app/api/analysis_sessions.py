import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import log_activity
from app.models.ai_model import AIModel
from app.models.analysis import AnalysisSession, ComplianceStat
from app.models.user import User
from app.models.video_source import VideoSource
from app.schemas.analysis import ComplianceStatOut, SessionCreate, SessionOut, SessionStatus
from app.services.analysis import finalize_session
from app.services.stream_manager import stream_manager
from app.api.video_sources import get_source_for_user

router = APIRouter(prefix="/analysis-sessions", tags=["Analysis Sessions"])


def get_session_for_user(db: Session, session_id: uuid.UUID, user: User) -> AnalysisSession:
    session = db.get(AnalysisSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesi analisis tidak ditemukan")
    get_source_for_user(db, session.source_id, user)   # 404 kalau bukan miliknya
    return session


@router.get("/", response_model=list[SessionOut])
def list_sessions(
    source_id: Optional[uuid.UUID] = None,
    status: Optional[SessionStatus] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(AnalysisSession).join(VideoSource, AnalysisSession.source_id == VideoSource.id)
    if current_user.role != "admin":
        q = q.filter(VideoSource.user_id == current_user.id)
    if source_id:
        q = q.filter(AnalysisSession.source_id == source_id)
    if status:
        q = q.filter(AnalysisSession.status == status)
    return q.order_by(AnalysisSession.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/stream-status/live")
def live_stream_status(current_user: User = Depends(get_current_user)):
    """Stream CCTV mana yang lagi jalan & connected (real-time, bukan dari DB)."""
    return stream_manager.status()


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    return get_session_for_user(db, session_id, current_user)


@router.post("/", response_model=SessionOut, status_code=201)
def create_session(payload: SessionCreate, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    """Buat sesi analisis (status queued). Jalankan lewat POST /{id}/start."""
    source = get_source_for_user(db, payload.source_id, current_user)

    if source.source_type == "video_upload" and source.expires_at and source.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Video unggahan sudah kedaluwarsa")
    if source.status == "maintenance":
        raise HTTPException(status_code=409, detail="Sumber video sedang maintenance")

    if payload.model_id:
        model = db.get(AIModel, payload.model_id)
        if model is None:
            raise HTTPException(status_code=422, detail="Model AI tidak ditemukan")
        if model.environment_id != source.environment_id:
            raise HTTPException(status_code=422, detail="Model AI bukan milik environment sumber video ini")
        if not model.is_active:
            raise HTTPException(status_code=422, detail="Model AI tidak aktif")
    else:
        model = (
            db.query(AIModel)
            .filter(AIModel.environment_id == source.environment_id, AIModel.is_active.is_(True))
            .order_by(AIModel.created_at.desc())
            .first()
        )
        if model is None:
            raise HTTPException(status_code=422, detail="Belum ada model AI aktif untuk environment sumber video ini")

    session = AnalysisSession(source_id=source.id, model_id=model.id, user_id=current_user.id, status="queued")
    db.add(session)
    db.flush()
    log_activity(db, current_user.id, "session.create", "analysis_session", session.id, source.name)
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/start", response_model=SessionOut)
def start_session(session_id: uuid.UUID, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    session = get_session_for_user(db, session_id, current_user)
    if session.status != "queued":
        raise HTTPException(status_code=409, detail=f"Sesi berstatus '{session.status}', hanya 'queued' yang bisa dimulai")

    source = db.get(VideoSource, session.source_id)
    busy = db.query(AnalysisSession).filter(
        AnalysisSession.source_id == source.id, AnalysisSession.status == "processing"
    ).first()
    if busy:
        raise HTTPException(status_code=409, detail="Sumber video ini masih punya sesi yang sedang berjalan")

    session.status = "processing"
    session.started_at = datetime.now(timezone.utc)
    if source.source_type == "cctv_stream":
        source.status = "active"
    log_activity(db, current_user.id, "session.start", "analysis_session", session.id, source.name)
    db.commit()

    if source.source_type == "cctv_stream":
        stream_manager.start(str(session.id), source.stream_url, source.target_fps)
    # video_upload: proses inferensi file diambil oleh worker AI (belum ada di repo ini)
    db.refresh(session)
    return session


@router.post("/{session_id}/stop", response_model=SessionOut)
def stop_session(session_id: uuid.UUID, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    session = get_session_for_user(db, session_id, current_user)
    if session.status != "processing":
        raise HTTPException(status_code=409, detail="Hanya sesi 'processing' yang bisa dihentikan")

    stream_manager.stop(str(session.id))
    source = db.get(VideoSource, session.source_id)
    if source.source_type == "cctv_stream":
        source.status = "inactive"
    finalize_session(db, session, "done")
    log_activity(db, current_user.id, "session.stop", "analysis_session", session.id, source.name)
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}/stats", response_model=list[ComplianceStatOut])
def session_stats(session_id: uuid.UUID, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    """Rangkuman kepatuhan per jam."""
    session = get_session_for_user(db, session_id, current_user)
    return (
        db.query(ComplianceStat)
        .filter(ComplianceStat.session_id == session.id)
        .order_by(ComplianceStat.bucket_start)
        .all()
    )
