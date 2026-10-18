"""Unit tests for Phase 10 Hardening: Rate Limiting, Payload Limits, Secret Rotation, Validation."""

from fastapi.testclient import TestClient
from server.rate_limiter import sample_rate_limiter


def test_payload_size_limit_rejects_large_payload(client: TestClient):
    """Verifies that payloads exceeding the limit are rejected with HTTP 413."""
    # Send a 100KB payload (exceeding 50KB limit)
    large_garbage = "x" * (100 * 1024)
    response = client.post(
        "/v1/samples",
        content=large_garbage,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert "Payload too large" in response.json()["detail"]


def test_rate_limiting_samples(client: TestClient):
    """Verifies that exceeding the burst rate limit triggers HTTP 429."""
    sample_rate_limiter.reset()

    # Create and claim a pairing
    create_resp = client.post("/v1/pairings", json={"pc_name": "Test-PC"})
    data = create_resp.json()
    pairing_id = data["pairing_id"]
    code = data["code"]
    secret = data["secret"]

    client.post(f"/v1/pairings/{code}/claim", json={"fcm_token": "valid_token_12345"})

    payload = {
        "pairing_id": pairing_id,
        "source": "chrome",
        "pc_name": "Test-PC",
        "downloads": [
            {
                "id": "dl-1",
                "filename": "test.iso",
                "bytes_downloaded": 100,
                "total_bytes": 1000,
                "state": "downloading",
            }
        ],
    }
    headers = {"Authorization": f"Bearer {secret}"}

    # Rapid burst of 15 requests
    status_codes = []
    for _ in range(15):
        resp = client.post("/v1/samples", json=payload, headers=headers)
        status_codes.append(resp.status_code)

    # First 10 requests should succeed (200), subsequent requests should return 429
    assert 200 in status_codes
    assert 429 in status_codes

    sample_rate_limiter.reset()


def test_secret_rotation(client: TestClient):
    """Verifies that rotating secret invalidates the old secret and activates the new one."""
    sample_rate_limiter.reset()

    # 1. Create and claim pairing
    create_resp = client.post("/v1/pairings", json={"pc_name": "Test-PC"})
    data = create_resp.json()
    pairing_id = data["pairing_id"]
    code = data["code"]
    old_secret = data["secret"]

    client.post(f"/v1/pairings/{code}/claim", json={"fcm_token": "token_for_rotation"})

    # 2. Sample dispatch with old secret succeeds
    sample_payload = {
        "pairing_id": pairing_id,
        "downloads": [
            {
                "id": "dl-1",
                "filename": "test.iso",
                "bytes_downloaded": 50,
                "state": "downloading",
            }
        ],
    }
    r_old = client.post(
        "/v1/samples",
        json=sample_payload,
        headers={"Authorization": f"Bearer {old_secret}"},
    )
    assert r_old.status_code == 200

    # 3. Rotate secret
    rotate_resp = client.post(
        f"/v1/pairings/{pairing_id}/rotate-secret",
        headers={"Authorization": f"Bearer {old_secret}"},
    )
    assert rotate_resp.status_code == 200
    rotate_data = rotate_resp.json()
    assert rotate_data["status"] == "ok"
    new_secret = rotate_data["new_secret"]
    assert new_secret != old_secret

    # 4. Old secret is now rejected (401)
    r_old_after = client.post(
        "/v1/samples",
        json=sample_payload,
        headers={"Authorization": f"Bearer {old_secret}"},
    )
    assert r_old_after.status_code == 401

    # 5. New secret succeeds (200)
    r_new = client.post(
        "/v1/samples",
        json=sample_payload,
        headers={"Authorization": f"Bearer {new_secret}"},
    )
    assert r_new.status_code == 200

    sample_rate_limiter.reset()


def test_input_validation_edge_cases(client: TestClient):
    """Verifies that invalid enum states or negative byte values are rejected with 422."""
    create_resp = client.post("/v1/pairings", json={"pc_name": "Test-PC"})
    data = create_resp.json()
    pairing_id = data["pairing_id"]
    code = data["code"]
    secret = data["secret"]
    client.post(f"/v1/pairings/{code}/claim", json={"fcm_token": "token123"})

    headers = {"Authorization": f"Bearer {secret}"}

    # Invalid state
    bad_state_payload = {
        "pairing_id": pairing_id,
        "downloads": [
            {
                "id": "dl-1",
                "filename": "test.iso",
                "bytes_downloaded": 50,
                "state": "invalid_state_xyz",
            }
        ],
    }
    assert client.post("/v1/samples", json=bad_state_payload, headers=headers).status_code == 422

    # Negative bytes downloaded
    negative_bytes_payload = {
        "pairing_id": pairing_id,
        "downloads": [
            {
                "id": "dl-1",
                "filename": "test.iso",
                "bytes_downloaded": -50,
                "state": "downloading",
            }
        ],
    }
    resp = client.post("/v1/samples", json=negative_bytes_payload, headers=headers)
    assert resp.status_code == 422
