import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # pelaku; jadi NULL kalau user pelakunya dihapus permanen
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)          # user.create, user.approve, source.upload, ...
    target_type = Column(String, nullable=True)      # user, video_source, ...
    target_id = Column(UUID(as_uuid=True), nullable=True)
    detail = Column(String, nullable=True)           # nama/username target, disalin saat aksi
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def log_activity(db, user_id, action, target_type=None, target_id=None, detail=None):
    """Tambah satu baris log ke session. Commit-nya dilakukan oleh pemanggil."""
    db.add(
        ActivityLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )