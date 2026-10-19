"""Unit and integration tests for authentication and authorized sample ingestion."""

from fastapi.testclient import TestClient

from server.tests.conftest import MockNotifier


def test_samples_endpoint_requires_auth(client: TestClient):
    payload = {
        "pairing_id": "pair-no-auth",
        "source": "chrome",
        "pc_name": "Test-PC",
        "downloads": [
            {
                "id": "dl-1",
                "filename": "test.bin",
                "bytes_downloaded": 100,
                "total_bytes": 1000,
                "state": "downloading",
            }
        ],
    }

    # Request without Authorization header
    resp = client.post("/v1/samples", json=payload)
    assert resp.status_code == 401
    assert "Missing Authorization" in resp.json()["detail"]


def test_samples_endpoint_with_invalid_bearer(client: TestClient):
    payload = {
        "pairing_id": "pair-bad-token",
        "source": "chrome",
        "pc_name": "Test-PC",
        "downloads": [
            {
                "id": "dl-1",
                "filename": "test.bin",
                "bytes_downloaded": 100,
                "total_bytes": 1000,
                "state": "downloading",
            }
        ],
    }

    resp = client.post(
        "/v1/samples",
        json=payload,
        headers={"Authorization": "Bearer invalid-secret-token-xyz"},
    )
    assert resp.status_code == 401
    assert "Invalid or expired" in resp.json()["detail"]


def test_samples_endpoint_with_valid_bearer(client: TestClient, mock_notifier: MockNotifier):
    # 1. Create pairing
    create_resp = client.post("/v1/pairings", json={"pc_name": "Authed-PC"})
    assert create_resp.status_code == 201
    pairing = create_resp.json()

    # 2. Claim pairing with phone FCM token
    claim_resp = client.post(
        f"/v1/pairings/{pairing['code']}/claim",
        json={"fcm_token": "fcm_target_device_token_456"},
    )
    assert claim_resp.status_code == 200

    # 3. Post sample with Bearer secret
    payload = {
        "pairing_id": pairing["pairing_id"],
        "source": "chrome",
        "pc_name": "Authed-PC",
        "downloads": [
            {
                "id": "dl-99",
                "filename": "ubuntu-desktop.iso",
                "bytes_downloaded": 500_000_000,
                "total_bytes": 1_000_000_000,
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
    assert resp.json()["status"] == "ok"

    # Verify mock notifier received the targeted token
    assert len(mock_notifier.dispatched) == 1
    assert mock_notifier.target_tokens[0] == "fcm_target_device_token_456"
