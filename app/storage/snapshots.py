"""Foto bukti pelanggaran di disk lokal: pemetaan path, penghapusan, dan hitung pemakaian.

Di database, image_url tetap disimpan sebagai '/snapshots/<session_id>/<file>.jpg' (kolom image_url).
Ke klien, URL itu diganti endpoint ber-auth /detection-logs/{id}/image (lihat snapshot_api_url).
Modul ini sengaja tidak mengimpor cv2 supaya ringan dipakai schema dan tes.
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings

PREFIX = "/snapshots/"


def snapshot_root() -> Path:
    return Path(settings.snapshot_dir)


def snapshot_api_url(log_id, image_url: Optional[str]) -> Optional[str]:
    """URL yang diberikan ke klien. None kalau log tidak punya foto."""
    return f"/detection-logs/{log_id}/image" if image_url else None


def snapshot_file(image_url: Optional[str]) -> Optional[Path]:
    """Path file di disk untuk image_url, atau None kalau formatnya tidak dikenal / keluar dari folder snapshot."""
    if not image_url or not image_url.startswith(PREFIX):
        return None
    root = snapshot_root().resolve()
    path = (root / image_url[len(PREFIX):]).resolve()
    return path if root in path.parents else None      # tolak ../ (path traversal)


def delete_snapshot_file(image_url: Optional[str]) -> bool:
    path = snapshot_file(image_url)
    if path is None or not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        print(f"[storage] gagal hapus snapshot {path}: {exc}")
        return False


def delete_session_snapshots(session_id) -> None:
    """Hapus seluruh folder foto bukti milik satu sesi."""
    try:
        sid = str(uuid.UUID(str(session_id)))     
    except ValueError:
        return
    shutil.rmtree(snapshot_root() / sid, ignore_errors=True)


def snapshot_usage() -> tuple[int, int]:
    """(total_byte, jumlah_file) seluruh foto bukti."""
    total = count = 0
    root = snapshot_root()
    if not root.exists():
        return 0, 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
                count += 1
            except OSError:
                pass
    return total, count