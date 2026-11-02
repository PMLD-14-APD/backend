"""Logika murni manajemen user (tanpa database), supaya gampang dites."""
import uuid
from typing import Iterable


def leaves_no_active_admin(active_admin_ids: Iterable[uuid.UUID], target_id: uuid.UUID) -> bool:
    """True kalau setelah `target_id` dinonaktifkan / dihapus / diturunkan rolenya,
    tidak ada lagi admin aktif yang tersisa."""
    return not any(admin_id != target_id for admin_id in active_admin_ids)