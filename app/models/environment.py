import uuid
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Location(Base):
    __tablename__ = "locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)

    # FK video_sources.location_id = ON DELETE SET NULL (dikerjakan database)
    video_sources = relationship("VideoSource", back_populates="location", passive_deletes=True)


class Environment(Base):
    __tablename__ = "environments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)   # misal: "Konstruksi"
    description = Column(String, nullable=True)

    video_sources = relationship("VideoSource", back_populates="environment")
    apd_requirements = relationship(
        "EnvironmentApdClass",
        back_populates="environment",
        cascade="all, delete-orphan",
    )
    # 1 environment : banyak model AI (1 model hanya milik 1 environment)
    ai_models = relationship("AIModel", back_populates="environment")
