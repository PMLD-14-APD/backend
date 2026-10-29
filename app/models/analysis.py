import uuid
from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

SESSION_STATUSES = ("queued", "processing", "done", "failed")
COMPLIANCE_STATUSES = ("kurang_lengkap", "tidak_digunakan")


class AnalysisSession(Base):
    """Satu kali proses analisis atas satu sumber video memakai satu model AI."""
    __tablename__ = "analysis_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("video_sources.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(UUID(as_uuid=True), ForeignKey("ai_models.id"), nullable=False)
    # pemicu; jadi NULL kalau user dihapus permanen
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    status = Column(String, nullable=False, default="queued")   # queued|processing|done|failed
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)  # NULL selama stream berjalan
    total_persons = Column(Integer, nullable=False, default=0)
    total_violations = Column(Integer, nullable=False, default=0)
    compliance_rate = Column(Float, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("VideoSource", back_populates="sessions")
    model = relationship("AIModel")
    user = relationship("User")
    stats = relationship("ComplianceStat", back_populates="session", passive_deletes=True)
    detection_logs = relationship("DetectionLog", back_populates="session", passive_deletes=True)


class ComplianceStat(Base):
    """Rangkuman kepatuhan per jam untuk satu sesi."""
    __tablename__ = "compliance_stats"
    __table_args__ = (
        Index("ix_compliance_stats_session_bucket", "session_id", "bucket_start"),
        Index("ix_compliance_stats_bucket_start", "bucket_start"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False)
    bucket_start = Column(DateTime(timezone=True), nullable=False)   # per jam
    total_persons = Column(Integer, nullable=False, default=0)
    lengkap = Column(Integer, nullable=False, default=0)
    kurang_lengkap = Column(Integer, nullable=False, default=0)
    tidak_digunakan = Column(Integer, nullable=False, default=0)

    session = relationship("AnalysisSession", back_populates="stats")


class DetectionLog(Base):
    """Satu pelanggaran (orang yang APD-nya kurang lengkap / tidak dipakai) pada satu frame."""
    __tablename__ = "detection_logs"
    __table_args__ = (
        Index("ix_detection_logs_session_detected", "session_id", "detected_at"),
        Index("ix_detection_logs_detected_at", "detected_at"),      
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False)
    track_id = Column(Integer, nullable=True)
    compliance_status = Column(String, nullable=False)   # kurang_lengkap | tidak_digunakan
    violation_type = Column(String, nullable=False)      # misal: NO_HELMET
    confidence = Column(Float, nullable=False)
    frame_number = Column(Integer, nullable=False)
    video_timestamp = Column(Float, nullable=False)      # detik dari awal video
    bbox = Column(JSON, nullable=False)                 # {"x":..,"y":..,"w":..,"h":..}
    image_url = Column(String, nullable=True)            # snapshot di MinIO
    detected_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("AnalysisSession", back_populates="detection_logs")
    items = relationship(
        "DetectionLogItem", back_populates="detection_log", passive_deletes=True,
        order_by="DetectionLogItem.id",
    )


class DetectionLogItem(Base):
    """Detail per kelas APD pada satu deteksi (dipakai / tidak)."""
    __tablename__ = "detection_log_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    detection_log_id = Column(BigInteger, ForeignKey("detection_logs.id", ondelete="CASCADE"), nullable=False)
    apd_class_id = Column(UUID(as_uuid=True), ForeignKey("apd_classes.id"), nullable=False)
    is_present = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)

    detection_log = relationship("DetectionLog", back_populates="items")
    apd_class = relationship("ApdClass")
