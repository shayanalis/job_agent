"""In-memory workflow status tracking service."""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List
from urllib.parse import urlparse

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

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._store: Dict[str, StatusSnapshot] = {}
        self._job_index: Dict[str, str] = {}
        self._hash_index: Dict[str, str] = {}
        self._order: List[str] = []

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

        with self._lock:
            self._evict_locked()
            self._store[status_id] = snapshot
            self._job_index[snapshot.job_url] = status_id
            self._index_hash(snapshot)
            self._touch_order(status_id)

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

            snapshot = None
            if status_id:
                snapshot = self._store.get(status_id)
            elif job_url:
                normalized_job = self.normalize_job_url(job_url)
                status_id = self._job_index.get(normalized_job)
                if status_id:
                    snapshot = self._store.get(status_id)

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
                self._store[snapshot.status_id] = snapshot
                self._job_index[snapshot.job_url] = snapshot.status_id
                self._index_hash(snapshot)
                self._touch_order(snapshot.status_id)
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

            return snapshot

    def get_status(
        self,
        *,
        status_id: Optional[str] = None,
        job_url: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Optional[StatusSnapshot]:
        with self._lock:
            self._evict_locked()

            if status_id:
                snapshot = self._store.get(status_id)
                if snapshot:
                    return snapshot

            if job_url:
                normalized = self.normalize_job_url(job_url)
                sid = self._job_index.get(normalized)
                if sid:
                    return self._store.get(sid)

            if base_url:
                normalized_base = self.normalize_base_url(base_url)
                for sid in reversed(self._order):
                    snapshot = self._store.get(sid)
                    if not snapshot:
                        continue
                    if snapshot.base_url == normalized_base:
                        return snapshot

            return None

    def get_by_hash(self, job_hash: str) -> Optional[StatusSnapshot]:
        with self._lock:
            self._evict_locked()
            sid = self._hash_index.get(job_hash)
            if not sid:
                return None
            return self._store.get(sid)

    def list_all(self, include_applied: bool = True) -> List[StatusSnapshot]:
        with self._lock:
            self._evict_locked()
            snapshots = [self._store[sid] for sid in self._order if sid in self._store]
            if not include_applied:
                snapshots = [
                    snap for snap in snapshots if not snap.metadata.get("applied", False)
                ]
            return list(snapshots)

    def mark_applied(self, status_id: str, applied: bool = True) -> Optional[StatusSnapshot]:
        with self._lock:
            self._evict_locked()
            snapshot = self._store.get(status_id)
            if not snapshot:
                return None
            snapshot.metadata["applied"] = applied
            snapshot.updated_at = time.time()
            self._touch_order(status_id)
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
        if not self._store:
            return

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

    def _index_hash(self, snapshot: StatusSnapshot) -> None:
        job_hash = snapshot.metadata.get("job_hash")
        if job_hash:
            self._hash_index[job_hash] = snapshot.status_id

    def _touch_order(self, status_id: str) -> None:
        if status_id in self._order:
            self._order.remove(status_id)
        self._order.append(status_id)


status_service = StatusService()
