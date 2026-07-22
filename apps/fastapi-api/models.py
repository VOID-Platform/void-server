import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, Enum, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database import Base


class AnalysisStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IncidentModel(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    fingerprint = Column(String, unique=True, nullable=False)
    trace_id = Column(String, nullable=False)
    execution_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    first_scene = Column(String, nullable=False)
    last_scene = Column(String, nullable=False)
    latest_report_id = Column(String, nullable=True)
    occurrence = Column(Integer, default=1)
    last_seen = Column(DateTime, nullable=False, server_default=func.now())
    analysis_status = Column(
        Enum(AnalysisStatus, name="AnalysisStatus", create_type=False),
        nullable=False,
        server_default="PENDING",
    )
    latest_labels = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reports = relationship("ReportModel", back_populates="incident", cascade="all, delete-orphan")


class ReportModel(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    model = Column(String, nullable=False)
    report = Column(JSONB, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("IncidentModel", back_populates="reports")
