"""Penyimpanan file video unggahan di disk lokal + pembersihan yang sudah kedaluwarsa."""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analysis import AnalysisSession
from app.models.video_source import VideoSource
from app.storage.snapshots import delete_session_snapshots

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


def uploads_used_bytes(db: Session) -> int:
    """Total ukuran video unggahan yang masih tersimpan (dihitung dari database, bukan dari disk)."""
    return db.query(func.coalesce(func.sum(VideoSource.file_size), 0)).filter(
        VideoSource.source_type == "video_upload"
    ).scalar() or 0


def purge_expired_uploads(db: Session) -> int:
    """Hapus sumber video unggahan yang lewat expires_at. Sesi & log ikut terhapus via CASCADE,
    foto buktinya dihapus dari disk setelah commit."""
    now = datetime.now(timezone.utc)
    expired = (
        db.query(VideoSource)
        .filter(VideoSource.source_type == "video_upload", VideoSource.expires_at < now)
        .all()
    )
    files, session_ids = [], []
    for src in expired:
        files.append(src.file_path)
        session_ids += [row.id for row in db.query(AnalysisSession.id).filter(AnalysisSession.source_id == src.id)]
        db.delete(src)
    db.commit()
    for path in files:
        delete_file(path)
    for sid in session_ids:
        delete_session_snapshots(sid)
    return len(expired)


def save_snapshot(session_id, frame, box, caption: str) -> str:
    """Simpan foto bukti (frame + kotak orang) dan return URL relatif untuk disimpan di image_url."""
    folder = Path(settings.snapshot_dir) / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    img = frame.copy()
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cv2.putText(img, caption, (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    name = f"{uuid.uuid4().hex}.jpg"
    cv2.imwrite(str(folder / name), img)
    return f"/snapshots/{session_id}/{name}"