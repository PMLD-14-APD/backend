import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id"), nullable=False)

    name = Column(String, nullable=False)              # misal: "Gerbang Utama"
    stream_url = Column(String, nullable=False)         # rtsp:// atau http://
    status = Column(String, default="inactive")         # active | inactive | maintenance
    target_fps = Column(Integer, default=5)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    location = relationship("Location", back_populates="cameras")
    environment = relationship("Environment", back_populates="cameras")
    detection_logs = relationship("DetectionLog", back_populates="camera")
