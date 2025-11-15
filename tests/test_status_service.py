import pytest

from src.services.status_service import StatusService
from src.services.status_repository import StatusRepository


@pytest.fixture
def sqlite_status_service(tmp_path):
    db_url = f"sqlite:///{tmp_path/'status.db'}"
    repo = StatusRepository(database_url=db_url)
    repo.create_schema()
    return StatusService(repository=repo)


def test_normalize_job_and_base_urls():
    service = StatusService()

    job_url = "HTTPS://Example.com/jobs/software-engineer/?ref=homepage"
    base_url = "https://Example.com/jobs/software-engineer/"

    assert service.normalize_job_url(job_url) == "https://example.com/jobs/software-engineer"
    assert service.normalize_job_url(base_url) == "https://example.com/jobs/software-engineer"
    assert service.normalize_base_url(job_url) == "https://example.com"


def test_create_update_and_lookup_status_by_id_and_url(sqlite_status_service):
    service = sqlite_status_service

    snapshot = service.create_status(
        "https://example.com/jobs/123",
        status="processing",
        step="received",
        metadata={"source": "test"},
    )

    assert snapshot.status_id
    assert snapshot.status == "processing"
    assert snapshot.step == "received"
    assert snapshot.metadata["source"] == "test"

    fetched_by_id = service.get_status(status_id=snapshot.status_id)
    assert fetched_by_id is not None
    assert fetched_by_id.status_id == snapshot.status_id

    fetched_by_job = service.get_status(job_url="https://example.com/jobs/123/")
    assert fetched_by_job is not None
    assert fetched_by_job.status_id == snapshot.status_id

    service.update_status(
        status_id=snapshot.status_id,
        status="completed",
        step="uploaded",
        message="Upload finished",
        resume_url="https://drive.google.com/file/d/abc123",
        metadata={"validation_score": 0.92},
    )

    updated = service.get_status(status_id=snapshot.status_id)
    assert updated.status == "completed"
    assert updated.step == "uploaded"
    assert updated.resume_url.endswith("abc123")
    assert updated.metadata["validation_score"] == 0.92


def test_get_status_by_base_url(sqlite_status_service):
    service = sqlite_status_service


def test_repository_lookup_used_when_cache_empty(sqlite_status_service):
    service = sqlite_status_service

    snapshot = service.create_status(
        "https://example.com/jobs/cache",
        status="processing",
        step="received",
    )

    # Clear in-memory cache to force repository path.
    service._store.clear()
    service._job_index.clear()
    service._hash_index.clear()
    service._order.clear()

    fetched = service.get_status(status_id=snapshot.status_id)
    assert fetched is not None
    assert fetched.status_id == snapshot.status_id

    snapshot = service.create_status(
        "https://careers.example.com/jobs/456",
        status="processing",
        step="received",
    )

    fetched = service.get_status(base_url="https://careers.example.com")
    assert fetched is not None
    assert fetched.status_id == snapshot.status_id

