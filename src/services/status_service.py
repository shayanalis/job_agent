"""SQLite-backed workflow status tracking service."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from src.services.status_repository import StatusRepository


@dataclass
class StatusSnapshot:
    """Represents the current workflow status for a job URL."""

    status_id: str
    job_url: str
    base_url: str
    status: str
    step: str
    message: str = ""
    resume_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_id": self.status_id,
            "job_url": self.job_url,
            "base_url": self.base_url,
            "status": self.status,
            "step": self.step,
            "message": self.message,
            "resume_url": self.resume_url,
            "metadata": self.metadata,
            "updated_at": self.updated_at,
        }


class StatusService:
    """Manage workflow status snapshots with SQLite as the single source of truth."""

    def __init__(self, repository: Optional[StatusRepository] = None) -> None:
        self._repository = repository or StatusRepository()

    @staticmethod
    def normalize_job_url(url: str) -> str:
        parsed = urlparse(url or "")
        if not parsed.netloc:
            return url or ""

        path = parsed.path.rstrip("/")
        normalized = f"{parsed.scheme or 'https'}://{parsed.netloc.lower()}{path}"
        return normalized

    @staticmethod
    def normalize_base_url(url: str) -> str:
        parsed = urlparse(url or "")
        if not parsed.netloc:
            return url or ""

        scheme = parsed.scheme or "https"
        return f"{scheme}://{parsed.netloc.lower()}"

    def create_status(
        self,
        job_url: str,
        *,
        status: str = "processing",
        step: str = "received",
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        job_hash: Optional[str] = None,
    ) -> StatusSnapshot:
        status_id = uuid.uuid4().hex
        snapshot = self._build_snapshot(
            status_id=status_id,
            job_url=job_url,
            status=status,
            step=step,
            message=message,
            metadata=metadata,
            job_hash=job_hash,
        )

        self._repository.upsert(snapshot)
        return snapshot

    def update_status(
        self,
        *,
        status_id: Optional[str] = None,
        job_url: Optional[str] = None,
        status: str,
        step: str,
        message: str = "",
        resume_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        applied: Optional[bool] = None,
        job_hash: Optional[str] = None,
    ) -> Optional[StatusSnapshot]:
        if not status_id and not job_url:
            raise ValueError("Either status_id or job_url is required to update status")

        snapshot = None
        if status_id:
            snapshot = self._repository.get_by_status_id(status_id)
        if snapshot is None and job_url:
            snapshot = self._repository.get_by_job_url(self.normalize_job_url(job_url))

        if snapshot is None and job_url:
            snapshot = self._build_snapshot(
                status_id=status_id or uuid.uuid4().hex,
                job_url=job_url,
                status=status,
                step=step,
                message=message,
                resume_url=resume_url,
                metadata=metadata,
                job_hash=job_hash,
            )
            self._repository.upsert(snapshot)
            return snapshot

        if snapshot is None:
            return None

        snapshot.status = status
        snapshot.step = step
        snapshot.message = message
        snapshot.resume_url = resume_url
        if metadata is not None:
            snapshot.metadata.update(metadata)
        if applied is not None:
            snapshot.metadata["applied"] = applied
        if job_hash:
            snapshot.metadata["job_hash"] = job_hash
        snapshot.updated_at = time.time()

        self._repository.upsert(snapshot)
        return snapshot

    def get_status(
        self,
        *,
        status_id: Optional[str] = None,
        job_url: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Optional[StatusSnapshot]:
        snapshot = None
        if status_id:
            snapshot = self._repository.get_by_status_id(status_id)
        if snapshot is None and job_url:
            snapshot = self._repository.get_by_job_url(self.normalize_job_url(job_url))
        if snapshot is None and base_url:
            snapshot = self._repository.get_by_base_url(self.normalize_base_url(base_url))
        return snapshot

    def get_by_hash(self, job_hash: str) -> Optional[StatusSnapshot]:
        return self._repository.get_by_hash(job_hash)

    def list_all(self, include_applied: bool = True) -> List[StatusSnapshot]:
        return self._repository.list_recent(include_applied=include_applied)

    def mark_applied(self, status_id: str, applied: bool = True) -> Optional[StatusSnapshot]:
        snapshot = self._repository.mark_applied(status_id, applied)
        return snapshot

    def _build_snapshot(
        self,
        *,
        status_id: str,
        job_url: str,
        status: str,
        step: str,
        message: str = "",
        resume_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        job_hash: Optional[str] = None,
    ) -> StatusSnapshot:
        normalized_job = self.normalize_job_url(job_url)
        normalized_base = self.normalize_base_url(job_url)
        snapshot_metadata = metadata.copy() if metadata else {}
        if job_hash:
            snapshot_metadata.setdefault("job_hash", job_hash)
        return StatusSnapshot(
            status_id=status_id,
            job_url=normalized_job,
            base_url=normalized_base,
            status=status,
            step=step,
            message=message,
            resume_url=resume_url,
            metadata=snapshot_metadata,
        )

    # Legacy methods removed; repository handles persistence exclusively.


status_service = StatusService()
