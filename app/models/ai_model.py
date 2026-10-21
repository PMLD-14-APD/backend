import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    weights_path = Column(String, nullable=False)     # path ke file .pt / .onnx
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ApdClass(Base):
    __tablename__ = "apd_classes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)              # misal: "Helm", "Rompi"
    description = Column(String, nullable=True)


class EnvironmentApdClass(Base):
    """Nentuin APD apa aja yang wajib di satu environment tertentu."""
    __tablename__ = "environment_apd_classes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environments.id"), nullable=False)
    apd_class_id = Column(UUID(as_uuid=True), ForeignKey("apd_classes.id"), nullable=False)
    is_mandatory = Column(Boolean, default=True)

    environment = relationship("Environment", back_populates="apd_requirements")
    apd_class = relationship("ApdClass")
