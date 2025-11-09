import pytest

from src.services.status_service import StatusService


@pytest.fixture
def status_client():
    from src.api import server

    original_service = server.status_service
    test_service = StatusService(ttl_seconds=60)
    server.status_service = test_service

    try:
        yield server.app.test_client(), test_service
    finally:
        server.status_service = original_service


def test_status_endpoint_not_found_returns_normalized_urls(status_client):
    client, _ = status_client

    response = client.get(
        "/status",
        query_string={
            "job_url": "https://Example.com/jobs/software-engineer/?ref=foo"
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "not_found"
    assert data["snapshot"]["job_url"] == "https://example.com/jobs/software-engineer"
    assert data["snapshot"]["base_url"] == "https://example.com"


def test_status_endpoint_returns_snapshot_by_status_id(status_client):
    client, service = status_client

    snapshot = service.create_status(
        "https://example.com/jobs/789",
        status="processing",
        step="received",
    )
    service.update_status(
        status_id=snapshot.status_id,
        status="processing",
        step="loading_pointers",
        message="Loading base resume pointers",
    )

    response = client.get("/status", query_string={"status_id": snapshot.status_id})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "success"
    assert data["snapshot"]["status_id"] == snapshot.status_id
    assert data["snapshot"]["step"] == "loading_pointers"


def test_status_endpoint_supports_base_url_lookup(status_client):
    client, service = status_client

    snapshot = service.create_status(
        "https://jobs.example.com/listing/1",
        status="processing",
        step="received",
    )

    response = client.get("/status", query_string={"base_url": "https://jobs.example.com"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "success"
    assert data["snapshot"]["status_id"] == snapshot.status_id

