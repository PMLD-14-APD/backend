import uuid
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

SOURCE_TYPES = ("cctv_stream", "video_upload")
SOURCE_STATUSES = ("active", "inactive", "maintenance", "uploaded")


class VideoSource(Base):
    """Sumber video: stream CCTV atau file video yang diunggah (kedaluwarsa 30 hari)."""
    __tablename__ = "video_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id"), nullable=False)

    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)          # cctv_stream | video_upload
    stream_url = Column(String, nullable=True)            # khusus cctv_stream
    file_path = Column(String, nullable=True)             # khusus video_upload
    file_size = Column(BigInteger, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    target_fps = Column(Integer, nullable=False, default=5)
    status = Column(String, nullable=False, default="inactive")  # active|inactive|maintenance|uploaded
    expires_at = Column(DateTime(timezone=True), nullable=True)  # created_at + 30 hari untuk upload
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    location = relationship("Location", back_populates="video_sources")
    environment = relationship("Environment", back_populates="video_sources")
    # FK analysis_sessions.source_id = ON DELETE CASCADE (dikerjakan database)
    sessions = relationship("AnalysisSession", back_populates="source", passive_deletes=True)
