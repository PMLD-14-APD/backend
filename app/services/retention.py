"""Pembersihan terjadwal: upload kedaluwarsa, foto bukti lama, riwayat lama, dan file yatim di disk.

Semua fungsi menerima Session SQLAlchemy dan aman dijalankan berulang. Nilai retensi 0 = nonaktif.
Urutan di run_cleanup: baris database dihapus + di-commit dulu, baru file di disk dihapus, jadi kalau
commit gagal tidak ada file yang hilang tanpa catatan.
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analysis import AnalysisSession, ComplianceStat, DetectionLog
from app.models.video_source import VideoSource
from app.storage import local
from app.storage.snapshots import delete_session_snapshots, delete_snapshot_file, snapshot_root

BATCH = 500
FINISHED_STATUSES = ("done", "failed")
ORPHAN_MIN_AGE_SECONDS = 3600      # file upload yang baru ditulis (< 1 jam) tidak disentuh


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def purge_old_snapshots(db: Session, days: int) -> int:
    """Hapus file foto bukti lebih tua dari `days` hari. Log pelanggarannya tetap ada (image_url jadi NULL)."""
    if days <= 0:
        return 0
    cutoff, total = _cutoff(days), 0
    while True:
        logs = (
            db.query(DetectionLog)
            .filter(DetectionLog.detected_at < cutoff, DetectionLog.image_url.isnot(None))
            .limit(BATCH).all()
        )
        if not logs:
            return total
        for log in logs:
            delete_snapshot_file(log.image_url)
            log.image_url = None
        db.commit()
        total += len(logs)


def purge_old_history(db: Session, days: int) -> dict:
    """Hapus log pelanggaran, statistik per jam, dan sesi selesai yang lebih tua dari `days` hari."""
    result = {"logs": 0, "stats": 0, "sessions": 0}
    if days <= 0:
        return result
    cutoff = _cutoff(days)

    while True:   # log pelanggaran (+ fotonya); detail per kelas ikut terhapus via CASCADE
        logs = db.query(DetectionLog).filter(DetectionLog.detected_at < cutoff).limit(BATCH).all()
        if not logs:
            break
        for log in logs:
            delete_snapshot_file(log.image_url)
            db.delete(log)
        db.commit()
        result["logs"] += len(logs)

    result["stats"] = (
        db.query(ComplianceStat).filter(ComplianceStat.bucket_start < cutoff).delete(synchronize_session=False)
    )
    db.commit()

    # hanya sesi yang sudah selesai; sesi CCTV yang masih berjalan tidak pernah dihapus
    ended = func.coalesce(AnalysisSession.finished_at, AnalysisSession.created_at)
    old_ids = [
        row.id for row in db.query(AnalysisSession.id)
        .filter(AnalysisSession.status.in_(FINISHED_STATUSES), ended < cutoff).all()
    ]
    for i in range(0, len(old_ids), BATCH):
        chunk = old_ids[i:i + BATCH]
        db.query(AnalysisSession).filter(AnalysisSession.id.in_(chunk)).delete(synchronize_session=False)
        db.commit()
        for sid in chunk:
            delete_session_snapshots(sid)
    result["sessions"] = len(old_ids)
    return result


def sweep_orphans(db: Session) -> dict:
    """Hapus folder foto bukti yang sesinya sudah tidak ada, dan file upload yang tidak dirujuk sumber video mana pun."""
    removed_dirs = removed_files = 0

    root = snapshot_root()
    if root.exists():
        candidates = {}
        for entry in root.iterdir():
            if entry.is_dir():
                try:
                    candidates[uuid.UUID(entry.name)] = entry
                except ValueError:
                    continue
        ids = list(candidates)
        alive = set()
        for i in range(0, len(ids), BATCH):
            alive |= {r.id for r in db.query(AnalysisSession.id).filter(AnalysisSession.id.in_(ids[i:i + BATCH]))}
        for sid, entry in candidates.items():
            if sid not in alive:
                delete_session_snapshots(sid)
                removed_dirs += 1

    upload_root = local.upload_root()
    referenced = {
        str(Path(r.file_path).resolve())
        for r in db.query(VideoSource.file_path).filter(VideoSource.file_path.isnot(None))
    }
    now = datetime.now().timestamp()
    for f in upload_root.iterdir():
        if not f.is_file() or str(f.resolve()) in referenced:
            continue
        if now - f.stat().st_mtime < ORPHAN_MIN_AGE_SECONDS:
            continue
        local.delete_file(str(f))
        removed_files += 1
    return {"orphan_snapshot_dirs": removed_dirs, "orphan_upload_files": removed_files}


def run_cleanup(db: Session) -> dict:
    """Jalankan semua pembersihan sesuai pengaturan; return ringkasan jumlah yang dihapus."""
    summary = {"expired_uploads": local.purge_expired_uploads(db)}
    summary["old_snapshots"] = purge_old_snapshots(db, settings.snapshot_retention_days)
    history = purge_old_history(db, settings.history_retention_days)
    summary.update({f"old_{k}": v for k, v in history.items()})
    summary.update(sweep_orphans(db))
    return summary