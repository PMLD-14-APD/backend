import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.camera import Camera
from app.models.user import User
from app.schemas.camera import CameraCreate, CameraOut
from app.services.camera_manager import camera_manager

router = APIRouter()


@router.get("/", response_model=list[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Camera).all()


@router.post("/", response_model=CameraOut)
def register_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    camera = Camera(**payload.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)

    if camera.status == "active":
        camera_manager.start_camera(str(camera.id), camera.stream_url, camera.target_fps)

    return camera


@router.post("/{camera_id}/start")
def start_camera(
    camera_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    camera.status = "active"
    db.commit()
    camera_manager.start_camera(str(camera.id), camera.stream_url, camera.target_fps)
    return {"message": f"Camera {camera_id} started"}


@router.post("/{camera_id}/stop")
def stop_camera(
    camera_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    camera.status = "inactive"
    db.commit()
    camera_manager.stop_camera(str(camera_id))
    return {"message": f"Camera {camera_id} stopped"}


@router.get("/status/live")
def live_status(current_user: User = Depends(get_current_user)):
    """Cek kamera mana aja yang lagi jalan & connected (real-time, bukan dari DB)."""
    return camera_manager.status()