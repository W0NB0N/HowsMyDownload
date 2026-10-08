"""Integration tests for FastAPI endpoints: /health and /v1/samples."""

from fastapi.testclient import TestClient
from server.tests.conftest import MockNotifier


def test_health_endpoint(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


def test_post_valid_sample(client: TestClient, mock_notifier: MockNotifier):
    # 1. Create a pairing
    create_resp = client.post("/v1/pairings", json={"pc_name": "Workstation"})
    assert create_resp.status_code == 201
    pairing = create_resp.json()

    payload = {
        "pairing_id": pairing["pairing_id"],
        "source": "chrome",
        "pc_name": "Workstation",
        "downloads": [
            {
                "id": "1001",
                "filename": "dataset.tar.gz",
                "bytes_downloaded": 25_000_000,
                "total_bytes": 100_000_000,
                "state": "downloading",
            }
        ],
    }

    resp = client.post(
        "/v1/samples",
        json=payload,
        headers={"Authorization": f"Bearer {pairing['secret']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["processed"] == 1
    assert data["pairing_id"] == pairing["pairing_id"]

    assert len(mock_notifier.dispatched) == 1
    dispatched = mock_notifier.dispatched[0]
    assert dispatched.seq == 1
    assert dispatched.downloads[0].percentage == 25.0


def test_post_malformed_sample_returns_422(client: TestClient):
    # 1. Create a pairing
    create_resp = client.post("/v1/pairings", json={"pc_name": "Workstation"})
    pairing = create_resp.json()

    # Missing required 'pairing_id' and 'downloads.id'
    bad_payload = {
        "source": "chrome",
        "downloads": [
            {
                "filename": "bad.zip",
                "state": "invalid_state",
            }
        ],
    }

    resp = client.post(
        "/v1/samples",
        json=bad_payload,
        headers={"Authorization": f"Bearer {pairing['secret']}"},
    )
    assert resp.status_code == 422
