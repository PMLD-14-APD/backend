from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import get_db
from app.models.camera import Camera
from app.services.camera_manager import camera_manager
from app.api import cameras, detection_logs, auth

# import semua model biar SQLAlchemy tau semua tabel pas create_all
from app.models import user, environment, ai_model, camera as camera_model, detection_log  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    db = next(get_db())
    active_cameras = db.query(Camera).filter(Camera.status == "active").all()
    for cam in active_cameras:
        camera_manager.start_camera(str(cam.id), cam.stream_url, cam.target_fps)
    print(f"[startup] {len(active_cameras)} kamera aktif ditarik streamnya")

    yield

    # --- Shutdown ---
    camera_manager.stop_all()
    print("[shutdown] semua stream kamera dihentikan")


app = FastAPI(title="APD Detection API", lifespan=lifespan)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(cameras.router, prefix="/cameras", tags=["Cameras"])
app.include_router(detection_logs.router, prefix="/detection-logs", tags=["Detection Logs"])


@app.get("/")
def root():
    return {"message": "APD Detection API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}