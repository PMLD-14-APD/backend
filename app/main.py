import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

from app.core.database import SessionLocal
from app.models.analysis import AnalysisSession
from app.models.video_source import VideoSource
from app.services.inference.manager import inference_manager
from app.services.retention import run_cleanup
from app.services.stream_manager import stream_manager
from app.storage.local import purge_expired_uploads
from app.api import (
    activity_logs, analysis_sessions, auth, dashboard, detection_logs, history, master_data, storage_admin, users,
    video_sources,
)

# import semua model biar SQLAlchemy tau semua tabel (dipakai alembic & relationship)
from app.models import user, activity_log, environment, ai_model, video_source, analysis  # noqa: F401


def _cleanup_once() -> None:
    db = SessionLocal()
    try:
        summary = run_cleanup(db)
        done = {k: v for k, v in summary.items() if v}
        if done:
            print(f"[cleanup] {done}")
    finally:
        db.close()


async def _cleanup_loop(interval_minutes: int) -> None:
    """Pembersihan terjadwal (retensi, kuota, file yatim). Berjalan di thread supaya tidak memblokir API."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await asyncio.to_thread(_cleanup_once)
        except Exception as exc:  # noqa: BLE001  - satu putaran gagal tidak boleh mematikan penjadwal
            print(f"[cleanup] gagal: {exc}")


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
                inference_manager.start(s.id)
                resumed += 1
            else:
                s.status = "failed"
                s.error_message = "Server restart saat sesi berjalan"
        db.commit()
        print(f"[startup] {resumed} stream CCTV dilanjutkan")
    finally:
        db.close()

    cleanup_task = (
        asyncio.create_task(_cleanup_loop(settings.cleanup_interval_minutes))
        if settings.cleanup_interval_minutes > 0 else None
    )

    yield

    # --- Shutdown ---
    if cleanup_task:
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task
    inference_manager.stop_all()  
    stream_manager.stop_all()
    print("[shutdown] semua stream & proses inferensi dihentikan")


app = FastAPI(title="APD Detection API", lifespan=lifespan)

# CORS: frontend di origin/port lain (mis. Vite :5173) boleh memanggil API ini.
# Autentikasi memakai header Authorization (bukan cookie), jadi allow_credentials dimatikan.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# foto bukti disimpan di folder ini, tapi TIDAK dilayani sebagai file statis:
# klien mengambilnya lewat GET /detection-logs/{id}/image yang wajib login
Path(settings.snapshot_dir).mkdir(parents=True, exist_ok=True)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users (Admin)"])
app.include_router(activity_logs.router)
app.include_router(storage_admin.router)
app.include_router(master_data.locations_router)
app.include_router(master_data.environments_router)
app.include_router(master_data.apd_classes_router)
app.include_router(master_data.ai_models_router)
app.include_router(video_sources.router)
app.include_router(analysis_sessions.router)
app.include_router(detection_logs.router)
app.include_router(dashboard.router)
app.include_router(history.router)


@app.get("/")
def root():
    return {"message": "APD Detection API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}