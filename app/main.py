from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import SessionLocal
from app.models.analysis import AnalysisSession
from app.models.video_source import VideoSource
from app.services.stream_manager import stream_manager
from app.storage.local import purge_expired_uploads
from app.api import analysis_sessions, auth, detection_logs, master_data, users, video_sources

# import semua model biar SQLAlchemy tau semua tabel (dipakai alembic & relationship)
from app.models import user, activity_log, environment, ai_model, video_source, analysis  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    db = SessionLocal()
    try:
        purged = purge_expired_uploads(db)
        if purged:
            print(f"[startup] {purged} video unggahan kedaluwarsa dihapus")

        # Sesi yang masih 'processing' saat server mati: stream CCTV disambung lagi,
        # sesi file upload ditandai gagal karena prosesnya ikut mati.
        resumed = 0
        for s in db.query(AnalysisSession).filter(AnalysisSession.status == "processing").all():
            src = db.get(VideoSource, s.source_id)
            if src and src.source_type == "cctv_stream" and src.stream_url:
                stream_manager.start(str(s.id), src.stream_url, src.target_fps)
                resumed += 1
            else:
                s.status = "failed"
                s.error_message = "Server restart saat sesi berjalan"
        db.commit()
        print(f"[startup] {resumed} stream CCTV dilanjutkan")
    finally:
        db.close()

    yield

    # --- Shutdown ---
    stream_manager.stop_all()
    print("[shutdown] semua stream dihentikan")


app = FastAPI(title="APD Detection API", lifespan=lifespan)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users (Admin)"])
app.include_router(master_data.locations_router)
app.include_router(master_data.environments_router)
app.include_router(master_data.apd_classes_router)
app.include_router(master_data.ai_models_router)
app.include_router(video_sources.router)
app.include_router(analysis_sessions.router)
app.include_router(detection_logs.router)


@app.get("/")
def root():
    return {"message": "APD Detection API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}
