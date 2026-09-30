import uuid
from sqlalchemy import Column, String, Float, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class DetectionLog(Base):
    __tablename__ = "detection_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id = Column(UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False)
    model_id = Column(UUID(as_uuid=True), ForeignKey("ai_models.id"), nullable=False)
    apd_class_id = Column(UUID(as_uuid=True), ForeignKey("apd_classes.id"), nullable=False)

    violation_type = Column(String, nullable=False)   # misal: "NO_HELMET"
    confidence = Column(Float, nullable=False)
    image_url = Column(String, nullable=True)          # link ke MinIO
    detected_at = Column(DateTime(timezone=True), server_default=func.now())

    camera = relationship("Camera", back_populates="detection_logs")
    model = relationship("AIModel")
    apd_class = relationship("ApdClass")
