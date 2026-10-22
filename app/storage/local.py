"""Penyimpanan file video unggahan di disk lokal + pembersihan yang sudah kedaluwarsa."""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.video_source import VideoSource

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def upload_root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_upload_path(original_name: str) -> Path:
    ext = Path(original_name).suffix.lower()
    return upload_root() / f"{uuid.uuid4().hex}{ext}"


def probe_video(path: Path) -> tuple[float | None, float | None]:
    """Return (durasi_detik, fps). None kalau file tidak bisa dibaca sebagai video."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None, None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0 or frames <= 0:
            return None, None
        return frames / fps, fps
    finally:
        cap.release()


def delete_file(path: str | None) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError as exc:
            print(f"[storage] gagal hapus {path}: {exc}")


def purge_expired_uploads(db: Session) -> int:
    """Hapus sumber video unggahan yang lewat expires_at (sesi & log ikut terhapus via CASCADE)."""
    now = datetime.now(timezone.utc)
    expired = (
        db.query(VideoSource)
        .filter(VideoSource.source_type == "video_upload", VideoSource.expires_at < now)
        .all()
    )
    for src in expired:
        delete_file(src.file_path)
        db.delete(src)
    db.commit()
    return len(expired)
