"""ORM models for status persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text

from src.db.base import Base


class StatusSnapshotModel(Base):
    """Database representation of a resume workflow snapshot."""

    __tablename__ = "status_snapshots"

    status_id = Column(String(64), primary_key=True)
    job_url = Column(String(2048), nullable=False, index=True)
    base_url = Column(String(512), nullable=False, index=True)
    job_hash = Column(String(128), nullable=True, index=True)
    status = Column(String(64), nullable=False)
    step = Column(String(128), nullable=False)
    message = Column(Text, nullable=False, default="")
    resume_url = Column(Text, nullable=False, default="")
    metadata_json = Column("metadata", Text, nullable=False, default="{}")
    applied = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_status_snapshots_base_url_updated_at", "base_url", "updated_at"),
    )

