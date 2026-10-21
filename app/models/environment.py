import uuid
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Location(Base):
    __tablename__ = "locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)

    cameras = relationship("Camera", back_populates="location")


class Environment(Base):
    __tablename__ = "environments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)          # misal: "Konstruksi"
    description = Column(String, nullable=True)

    cameras = relationship("Camera", back_populates="environment")
    apd_requirements = relationship("EnvironmentApdClass", back_populates="environment")
