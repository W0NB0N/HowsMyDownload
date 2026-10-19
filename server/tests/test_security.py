"""Security tests: per-pairing authorization, input validation, rate limits, body limits."""

import pytest
from fastapi.testclient import TestClient

from server.auth import hash_secret
from server.main import MAX_BODY_BYTES
from server.tests.conftest import MockNotifier, create_claimed_pairing

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def _sample(pairing_id: str) -> dict:
    return {
        "pairing_id": pairing_id,
        "downloads": [
            {"id": "d1", "filename": "enc:v1:a:b", "bytes_downloaded": 5, "state": "downloading"}
        ],
    }


# --- Unpair (DELETE) ---------------------------------------------------------------


def test_delete_requires_credentials(client: TestClient):
    pairing = create_claimed_pairing(client)
    url = f"/v1/pairings/{pairing['pairing_id']}"

    assert client.delete(url).status_code == 401
    assert client.delete(url, headers=_bearer("guessed")).status_code == 401
    # Still paired: the extension secret keeps working
    assert client.get(url, headers=_bearer(pairing["secret"])).status_code == 200


def test_delete_with_another_pairings_secret_is_rejected(client: TestClient):
    victim = create_claimed_pairing(client, fcm_token="victim")
    attacker = create_claimed_pairing(client, fcm_token="attacker")
    url = f"/v1/pairings/{victim['pairing_id']}"

    assert client.delete(url, headers=_bearer(attacker["secret"])).status_code == 401
    assert client.delete(url, headers=_bearer(attacker["device_secret"])).status_code == 401
    assert client.get(url, headers=_bearer(victim["secret"])).status_code == 200


def test_device_can_unpair_and_phone_is_not_pinged(client: TestClient, mock_notifier: MockNotifier):
    pairing = create_claimed_pairing(client)
    url = f"/v1/pairings/{pairing['pairing_id']}"

    assert client.delete(url, headers=_bearer(pairing["device_secret"])).status_code == 200
    assert mock_notifier.unpair_events == []
    assert client.get(url, headers=_bearer(pairing["secret"])).status_code == 401


def test_extension_unpair_notifies_phone(client: TestClient, mock_notifier: MockNotifier):
    pairing = create_claimed_pairing(client, fcm_token="phone-token")
    url = f"/v1/pairings/{pairing['pairing_id']}"

    assert client.delete(url, headers=_bearer(pairing["secret"])).status_code == 200
    assert mock_notifier.unpair_events == [("phone-token", pairing["pairing_id"])]


def test_unpair_drops_tracker_state(client: TestClient):
    pairing = create_claimed_pairing(client)
    tracker = client.app.state.tracker_manager
    resp = client.post(
        "/v1/samples", json=_sample(pairing["pairing_id"]), headers=_bearer(pairing["secret"])
    )
    assert resp.status_code == 200
    assert tracker.get_active_count(pairing["pairing_id"]) == 1

    client.delete(f"/v1/pairings/{pairing['pairing_id']}", headers=_bearer(pairing["secret"]))
    assert tracker.get_active_count(pairing["pairing_id"]) == 0


# --- Role separation -----------------------------------------------------------------


def test_device_secret_cannot_send_samples_or_rotate(client: TestClient):
    pairing = create_claimed_pairing(client)
    device = _bearer(pairing["device_secret"])

    resp = client.post("/v1/samples", json=_sample(pairing["pairing_id"]), headers=device)
    assert resp.status_code == 401
    rotate = client.post(f"/v1/pairings/{pairing['pairing_id']}/rotate-secret", headers=device)
    assert rotate.status_code == 403


def test_device_secret_survives_extension_rotation(client: TestClient):
    pairing = create_claimed_pairing(client)
    pid = pairing["pairing_id"]
    rotated = client.post(f"/v1/pairings/{pid}/rotate-secret", headers=_bearer(pairing["secret"]))
    assert rotated.status_code == 200

    resp = client.post(
        f"/v1/pairings/{pid}/token",
        json={"fcm_token": "new"},
        headers=_bearer(pairing["device_secret"]),
    )
    assert resp.status_code == 200


def test_status_with_device_secret(client: TestClient):
    pairing = create_claimed_pairing(client)
    resp = client.get(
        f"/v1/pairings/{pairing['pairing_id']}", headers=_bearer(pairing["device_secret"])
    )
    assert resp.status_code == 200
    assert resp.json()["is_claimed"] is True


# --- Secret storage & expiry ----------------------------------------------------------


@pytest.mark.asyncio
async def test_secrets_are_stored_only_as_hashes(client: TestClient):
    pairing = create_claimed_pairing(client)
    record = await client.app.state.pairing_store.get_pairing(pairing["pairing_id"])

    dumped = record.model_dump_json()
    assert pairing["secret"] not in dumped
    assert pairing["device_secret"] not in dumped
    assert record.secret_hash == hash_secret(pairing["secret"])
    assert record.device_secret_hash == hash_secret(pairing["device_secret"])


@pytest.mark.asyncio
async def test_unclaimed_expired_pairing_secret_is_rejected(client: TestClient):
    store = client.app.state.pairing_store
    await store.create_pairing(
        pairing_id=UNKNOWN_ID,
        code="OLDQR1",
        secret_hash=hash_secret("abandoned-qr-secret"),
        pc_name="PC",
        expires_in_sec=-1,
    )
    resp = client.post(
        "/v1/samples", json=_sample(UNKNOWN_ID), headers=_bearer("abandoned-qr-secret")
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_unclaimed_pairings_are_purged(client: TestClient):
    store = client.app.state.pairing_store
    await store.create_pairing(
        pairing_id=UNKNOWN_ID, code="OLDQR2", secret_hash="h", pc_name="PC", expires_in_sec=-1
    )
    client.post("/v1/pairings", json={"pc_name": "New-PC"})
    assert await store.get_pairing(UNKNOWN_ID) is None


# --- Input validation -----------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "1234", "../../etc", "x" * 36])
def test_malformed_pairing_ids_rejected(client: TestClient, bad_id: str):
    pairing = create_claimed_pairing(client)
    resp = client.get(f"/v1/pairings/{bad_id}", headers=_bearer(pairing["secret"]))
    assert resp.status_code in (404, 422)
    assert resp.status_code != 200


@pytest.mark.parametrize("bad_code", ["ABC", "ABCDEFG", "AB$DEF"])
def test_malformed_claim_codes_rejected(client: TestClient, bad_code: str):
    resp = client.post(f"/v1/pairings/{bad_code}/claim", json={"fcm_token": "t"})
    assert resp.status_code == 422


def test_claim_code_is_case_insensitive(client: TestClient):
    created = client.post("/v1/pairings", json={"pc_name": "PC"}).json()
    resp = client.post(f"/v1/pairings/{created['code'].lower()}/claim", json={"fcm_token": "t"})
    assert resp.status_code == 200


def test_unknown_pairing_returns_401_not_404(client: TestClient):
    pairing = create_claimed_pairing(client)
    resp = client.get(f"/v1/pairings/{UNKNOWN_ID}", headers=_bearer(pairing["secret"]))
    assert resp.status_code == 401


# --- Rate limiting --------------------------------------------------------------------


def test_claim_endpoint_is_rate_limited_per_ip(client: TestClient):
    statuses = [
        client.post("/v1/pairings/ZZZZZZ/claim", json={"fcm_token": "t"}).status_code
        for _ in range(12)
    ]
    assert statuses[:10] == [400] * 10
    assert statuses[10:] == [429, 429]


def test_pairing_creation_is_rate_limited_per_ip(client: TestClient):
    statuses = [
        client.post("/v1/pairings", json={"pc_name": "PC"}).status_code for _ in range(11)
    ]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


def test_sample_rate_limit_sets_retry_after(client: TestClient):
    pairing = create_claimed_pairing(client)
    headers = _bearer(pairing["secret"])
    responses = [
        client.post("/v1/samples", json=_sample(pairing["pairing_id"]), headers=headers)
        for _ in range(11)
    ]
    assert [r.status_code for r in responses[:10]] == [200] * 10
    limited = responses[10]
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 10


def test_sample_rate_limit_is_per_pairing(client: TestClient):
    a = create_claimed_pairing(client)
    b = create_claimed_pairing(client)
    for _ in range(10):
        client.post("/v1/samples", json=_sample(a["pairing_id"]), headers=_bearer(a["secret"]))
    resp = client.post("/v1/samples", json=_sample(b["pairing_id"]), headers=_bearer(b["secret"]))
    assert resp.status_code == 200


# --- Body size limit ------------------------------------------------------------------


def test_chunked_oversized_body_is_rejected(client: TestClient):
    """No Content-Length header: the limit must still apply to the streamed body."""

    def chunks():
        for _ in range(MAX_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    resp = client.post(
        "/v1/samples", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413


def test_chunked_small_body_is_processed(client: TestClient):
    import json

    pairing = create_claimed_pairing(client)
    body = json.dumps(_sample(pairing["pairing_id"])).encode()

    def chunks():
        yield body[:10]
        yield body[10:]

    resp = client.post(
        "/v1/samples",
        content=chunks(),
        headers={"Content-Type": "application/json", **_bearer(pairing["secret"])},
    )
    assert resp.status_code == 200


def test_invalid_content_length_is_rejected(client: TestClient):
    resp = client.post("/v1/samples", content=b"{}", headers={"Content-Length": "abc"})
    assert resp.status_code in (400, 413)


# --- CORS -----------------------------------------------------------------------------


def test_cors_never_allows_credentials(client: TestClient):
    resp = client.options(
        "/v1/samples",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert resp.headers.get("access-control-allow-credentials") != "true"
