"""Database repository for status snapshots."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Iterable, List, Optional, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import DATABASE_URL
from src.db.base import Base, get_engine, get_session_factory
from src.db.models import StatusSnapshotModel

if TYPE_CHECKING:  # pragma: no cover
    from src.services.status_service import StatusSnapshot


class StatusRepository:
    """Encapsulates persistence logic for workflow status snapshots."""

    def __init__(self, database_url: str = DATABASE_URL) -> None:
        self._engine = get_engine(database_url)
        self._session_factory = get_session_factory(database_url)

    def create_schema(self) -> None:
        Base.metadata.create_all(bind=self._engine)

    @contextmanager
    def session_scope(self) -> Iterable[Session]:
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert(self, snapshot: "StatusSnapshot") -> None:
        metadata = (snapshot.metadata or {}).copy()
        applied = bool(metadata.get("applied", False))
        now_dt = datetime.utcfromtimestamp(snapshot.updated_at)
        metadata_json = json.dumps(metadata)
        job_hash = metadata.get("job_hash")

        with self.session_scope() as session:
            model = session.get(StatusSnapshotModel, snapshot.status_id)
            if model is None:
                model = StatusSnapshotModel(
                    status_id=snapshot.status_id,
                    created_at=now_dt,
                )
            model.job_url = snapshot.job_url
            model.base_url = snapshot.base_url
            model.job_hash = job_hash
            model.status = snapshot.status
            model.step = snapshot.step
            model.message = snapshot.message
            model.resume_url = snapshot.resume_url
            model.metadata_json = metadata_json
            model.applied = applied
            model.updated_at = now_dt
            session.add(model)

    def get_by_status_id(self, status_id: str) -> Optional["StatusSnapshot"]:
        with self.session_scope() as session:
            model = session.get(StatusSnapshotModel, status_id)
            return self._model_to_snapshot(model)

    def get_by_job_url(self, job_url: str) -> Optional["StatusSnapshot"]:
        stmt = (
            select(StatusSnapshotModel)
            .where(StatusSnapshotModel.job_url == job_url)
            .order_by(StatusSnapshotModel.updated_at.desc())
            .limit(1)
        )
        with self.session_scope() as session:
            model = session.scalars(stmt).first()
            return self._model_to_snapshot(model)

    def get_by_base_url(self, base_url: str) -> Optional["StatusSnapshot"]:
        stmt = (
            select(StatusSnapshotModel)
            .where(StatusSnapshotModel.base_url == base_url)
            .order_by(StatusSnapshotModel.updated_at.desc())
            .limit(1)
        )
        with self.session_scope() as session:
            model = session.scalars(stmt).first()
            return self._model_to_snapshot(model)

    def get_by_hash(self, job_hash: str) -> Optional["StatusSnapshot"]:
        stmt = (
            select(StatusSnapshotModel)
            .where(StatusSnapshotModel.job_hash == job_hash)
            .order_by(StatusSnapshotModel.updated_at.desc())
            .limit(1)
        )
        with self.session_scope() as session:
            model = session.scalars(stmt).first()
            return self._model_to_snapshot(model)

    def list_recent(self, include_applied: bool = True) -> List["StatusSnapshot"]:
        stmt = select(StatusSnapshotModel).order_by(StatusSnapshotModel.updated_at.desc())
        if not include_applied:
            stmt = stmt.where(StatusSnapshotModel.applied.is_(False))

        with self.session_scope() as session:
            models = session.scalars(stmt).all()
            return [snap for snap in map(self._model_to_snapshot, models) if snap is not None]

    def mark_applied(self, status_id: str, applied: bool) -> Optional["StatusSnapshot"]:
        with self.session_scope() as session:
            model = session.get(StatusSnapshotModel, status_id)
            if model is None:
                return None
            model.applied = applied
            metadata = self._deserialize_metadata(model.metadata_json)
            metadata["applied"] = applied
            model.metadata_json = json.dumps(metadata)
            model.updated_at = datetime.utcnow()
            session.add(model)
            session.flush()
            return self._model_to_snapshot(model)

    def _model_to_snapshot(self, model: Optional[StatusSnapshotModel]) -> Optional["StatusSnapshot"]:
        if model is None:
            return None
        from src.services.status_service import StatusSnapshot

        metadata = self._deserialize_metadata(model.metadata_json)
        metadata.setdefault("job_hash", model.job_hash)
        metadata["applied"] = bool(model.applied)
        return StatusSnapshot(
            status_id=model.status_id,
            job_url=model.job_url,
            base_url=model.base_url,
            status=model.status,
            step=model.step,
            message=model.message,
            resume_url=model.resume_url,
            metadata=metadata,
            updated_at=model.updated_at.timestamp(),
        )

    @staticmethod
    def _deserialize_metadata(raw: Optional[str]) -> dict:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

