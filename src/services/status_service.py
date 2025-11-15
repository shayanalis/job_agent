"""In-memory workflow status tracking service."""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from src.services.status_repository import StatusRepository

DEFAULT_TTL_SECONDS = 60 * 60  # 1 hour


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
    """Manage workflow status snapshots keyed by job URL and status_id."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        repository: Optional[StatusRepository] = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._store: Dict[str, StatusSnapshot] = {}
        self._job_index: Dict[str, str] = {}
        self._hash_index: Dict[str, str] = {}
        self._order: List[str] = []
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
        with self._lock:
            self._evict_locked()
            self._cache_snapshot_locked(snapshot)

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

        with self._lock:
            self._evict_locked()

            snapshot = self._lookup_locked(
                status_id=status_id,
                job_url=job_url,
            )

            if snapshot is None and job_url:
                # Create snapshot if missing on first update
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
                self._cache_snapshot_locked(snapshot)
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
                self._hash_index[job_hash] = snapshot.status_id
            snapshot.updated_at = time.time()
            self._touch_order(snapshot.status_id)

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
        with self._lock:
            self._evict_locked()
            snapshot = self._lookup_locked(
                status_id=status_id,
                job_url=job_url,
                base_url=base_url,
            )
            if snapshot:
                return snapshot

        if status_id:
            snapshot = self._repository.get_by_status_id(status_id)
        if snapshot is None and job_url:
            snapshot = self._repository.get_by_job_url(self.normalize_job_url(job_url))
        if snapshot is None and base_url:
            snapshot = self._repository.get_by_base_url(self.normalize_base_url(base_url))

        if snapshot:
            with self._lock:
                self._cache_snapshot_locked(snapshot)
        return snapshot

    def get_by_hash(self, job_hash: str) -> Optional[StatusSnapshot]:
        with self._lock:
            self._evict_locked()
            sid = self._hash_index.get(job_hash)
            if not sid:
                snapshot = None
            else:
                snapshot = self._store.get(sid)

        if snapshot:
            return snapshot

        snapshot = self._repository.get_by_hash(job_hash)
        if snapshot:
            with self._lock:
                self._cache_snapshot_locked(snapshot)
        return snapshot

    def list_all(self, include_applied: bool = True) -> List[StatusSnapshot]:
        snapshots = self._repository.list_recent(include_applied=include_applied)
        with self._lock:
            self._evict_locked()
            for snapshot in snapshots:
                self._cache_snapshot_locked(snapshot)
        return list(snapshots)

    def mark_applied(self, status_id: str, applied: bool = True) -> Optional[StatusSnapshot]:
        with self._lock:
            self._evict_locked()
            snapshot = self._store.get(status_id)
            if snapshot:
                snapshot.metadata["applied"] = applied
                snapshot.updated_at = time.time()
                self._touch_order(status_id)

        if snapshot:
            self._repository.upsert(snapshot)
            return snapshot

        snapshot = self._repository.mark_applied(status_id, applied)
        if snapshot:
            with self._lock:
                self._cache_snapshot_locked(snapshot)
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

    def _evict_locked(self) -> None:
        now = time.time()
        keys_to_delete = [
            key
            for key, snapshot in self._store.items()
            if now - snapshot.updated_at > self._ttl_seconds
        ]
        for key in keys_to_delete:
            snapshot = self._store.pop(key, None)
            if snapshot:
                self._job_index.pop(snapshot.job_url, None)
                job_hash = snapshot.metadata.get("job_hash")
                if job_hash and self._hash_index.get(job_hash) == key:
                    self._hash_index.pop(job_hash, None)
                if key in self._order:
                    self._order.remove(key)
        self._repository.evict_older_than(self._ttl_seconds)

    def _index_hash(self, snapshot: StatusSnapshot) -> None:
        job_hash = snapshot.metadata.get("job_hash")
        if job_hash:
            self._hash_index[job_hash] = snapshot.status_id

    def _touch_order(self, status_id: str) -> None:
        if status_id in self._order:
            self._order.remove(status_id)
        self._order.append(status_id)

    def _cache_snapshot_locked(self, snapshot: StatusSnapshot) -> None:
        self._store[snapshot.status_id] = snapshot
        self._job_index[snapshot.job_url] = snapshot.status_id
        self._index_hash(snapshot)
        self._touch_order(snapshot.status_id)

    def _lookup_locked(
        self,
        *,
        status_id: Optional[str] = None,
        job_url: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Optional[StatusSnapshot]:
        if status_id:
            snapshot = self._store.get(status_id)
            if snapshot:
                return snapshot

        if job_url:
            normalized = self.normalize_job_url(job_url)
            sid = self._job_index.get(normalized)
            if sid:
                snapshot = self._store.get(sid)
                if snapshot:
                    return snapshot

        if base_url:
            normalized_base = self.normalize_base_url(base_url)
            for sid in reversed(self._order):
                snapshot = self._store.get(sid)
                if snapshot and snapshot.base_url == normalized_base:
                    return snapshot

        return None


status_service = StatusService()
