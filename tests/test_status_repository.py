import time

from src.services.status_repository import StatusRepository
from src.services.status_service import StatusSnapshot


def create_repo(tmp_path):
    db_url = f"sqlite:///{tmp_path/'repo.db'}"
    repo = StatusRepository(database_url=db_url)
    repo.create_schema()
    return repo


def test_upsert_and_fetch_status_snapshot(tmp_path):
    repo = create_repo(tmp_path)

    snapshot = StatusSnapshot(
        status_id="snap-1",
        job_url="https://example.com/jobs/1",
        base_url="https://example.com",
        status="processing",
        step="received",
        message="",
        resume_url="",
        metadata={"job_hash": "hash-1"},
        updated_at=time.time(),
    )

    repo.upsert(snapshot)

    fetched = repo.get_by_status_id("snap-1")
    assert fetched is not None
    assert fetched.job_url == snapshot.job_url

    by_job = repo.get_by_job_url(snapshot.job_url)
    assert by_job is not None
    assert by_job.status_id == snapshot.status_id


def test_list_recent_and_eviction(tmp_path):
    repo = create_repo(tmp_path)

    old_snapshot = StatusSnapshot(
        status_id="old",
        job_url="https://example.com/jobs/old",
        base_url="https://example.com",
        status="completed",
        step="uploaded",
        message="",
        resume_url="",
        metadata={"job_hash": "old-hash"},
        updated_at=time.time() - 7200,
    )
    repo.upsert(old_snapshot)

    new_snapshot = StatusSnapshot(
        status_id="new",
        job_url="https://example.com/jobs/new",
        base_url="https://example.com",
        status="processing",
        step="writing_resume",
        message="",
        resume_url="",
        metadata={"job_hash": "new-hash", "applied": True},
        updated_at=time.time(),
    )
    repo.upsert(new_snapshot)

    recent = repo.list_recent(include_applied=False)
    assert len(recent) == 0  # filtered out because applied=True

    repo.evict_older_than(3600)
    assert repo.get_by_status_id("old") is None
    assert repo.get_by_status_id("new") is not None

