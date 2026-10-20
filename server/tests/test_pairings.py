"""Unit and integration tests for pairing endpoints and store."""

import pytest
from fastapi.testclient import TestClient

from server.auth import hash_secret
from server.store.memory import InMemoryPairingStore


def test_create_pairing(client: TestClient):
    resp = client.post("/v1/pairings", json={"pc_name": "Test-Rig"})
    assert resp.status_code == 201
    data = resp.json()

    assert "pairing_id" in data
    assert "code" in data
    assert len(data["code"]) == 6
    assert "secret" in data
    assert len(data["secret"]) >= 32
    assert "expires_at" in data


def test_claim_pairing_success(client: TestClient):
    create_resp = client.post("/v1/pairings", json={"pc_name": "Laptop-Work"})
    pairing_data = create_resp.json()
    code = pairing_data["code"]

    claim_resp = client.post(
        f"/v1/pairings/{code}/claim",
        json={"fcm_token": "fcm_test_device_token_123"},
    )
    assert claim_resp.status_code == 200
    claim_data = claim_resp.json()
    assert claim_data["status"] == "ok"
    assert claim_data["pairing_id"] == pairing_data["pairing_id"]
    assert claim_data["pc_name"] == "Laptop-Work"
    assert len(claim_data["device_secret"]) >= 32
    assert claim_data["device_secret"] != pairing_data["secret"]

    # Verify status via GET with Bearer token
    status_resp = client.get(
        f"/v1/pairings/{pairing_data['pairing_id']}",
        headers={"Authorization": f"Bearer {pairing_data['secret']}"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["is_claimed"] is True


def test_claim_pairing_duplicate_fails(client: TestClient):
    create_resp = client.post("/v1/pairings", json={"pc_name": "PC-1"})
    code = create_resp.json()["code"]

    # First claim succeeds
    r1 = client.post(f"/v1/pairings/{code}/claim", json={"fcm_token": "tok1"})
    assert r1.status_code == 200

    # Second claim fails
    r2 = client.post(f"/v1/pairings/{code}/claim", json={"fcm_token": "tok2"})
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_claim_expired_code_fails(pairing_store: InMemoryPairingStore):
    # Store directly with expired timestamp
    pairing_id = "pair-expired"
    code = "EXP999"
    secret = "secret123"
    await pairing_store.create_pairing(
        pairing_id=pairing_id,
        code=code,
        secret_hash=hash_secret(secret),
        pc_name="Old-PC",
        expires_in_sec=-10,  # Already expired
    )

    claimed = await pairing_store.claim_pairing(code, "token_xyz", hash_secret("device"))
    assert claimed is None


@pytest.mark.asyncio
async def test_claim_max_attempts_exceeded(pairing_store: InMemoryPairingStore):
    pairing_id = "pair-attempts"
    code = "TRY555"
    secret = "secret456"
    record = await pairing_store.create_pairing(
        pairing_id=pairing_id,
        code=code,
        secret_hash=hash_secret(secret),
        pc_name="Sec-PC",
        expires_in_sec=300,
    )
    record.claim_attempts = 5

    claimed = await pairing_store.claim_pairing(code, "token_xyz", hash_secret("device"))
    assert claimed is None


def test_delete_pairing(client: TestClient):
    create_resp = client.post("/v1/pairings", json={"pc_name": "PC-Delete"})
    pairing_data = create_resp.json()
    p_id = pairing_data["pairing_id"]
    secret = pairing_data["secret"]

    del_resp = client.delete(
        f"/v1/pairings/{p_id}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    # Status check now fails
    status_resp = client.get(
        f"/v1/pairings/{p_id}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert status_resp.status_code == 401
