"""FCM token refresh: only the paired phone (device secret) may change where pushes go."""

import pytest

from server.tests.conftest import create_claimed_pairing


@pytest.mark.asyncio
async def test_token_refresh_requires_device_secret(client):
    pairing = create_claimed_pairing(client, fcm_token="original-token")
    pairing_id = pairing["pairing_id"]
    url = f"/v1/pairings/{pairing_id}/token"
    body = {"fcm_token": "rotated-fcm-token-999"}

    # No credential, a wrong credential, or the extension's credential cannot redirect pushes
    assert client.post(url, json=body).status_code == 401
    bad = {"Authorization": "Bearer not-a-real-secret"}
    assert client.post(url, json=body, headers=bad).status_code == 401
    ext = {"Authorization": f"Bearer {pairing['secret']}"}
    assert client.post(url, json=body, headers=ext).status_code == 403

    store = client.app.state.pairing_store
    assert (await store.get_pairing(pairing_id)).fcm_token == "original-token"

    # The phone's own secret works
    device = {"Authorization": f"Bearer {pairing['device_secret']}"}
    resp = client.post(url, json=body, headers=device)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "pairing_id": pairing_id}
    assert (await store.get_pairing(pairing_id)).fcm_token == "rotated-fcm-token-999"


def test_token_refresh_unknown_pairing_is_indistinguishable(client):
    pairing = create_claimed_pairing(client)
    device = {"Authorization": f"Bearer {pairing['device_secret']}"}
    unknown = "00000000-0000-4000-8000-000000000000"
    resp = client.post(f"/v1/pairings/{unknown}/token", json={"fcm_token": "x"}, headers=device)
    assert resp.status_code == 401


def test_token_refresh_rejects_malformed_pairing_id(client):
    resp = client.post("/v1/pairings/not-a-uuid/token", json={"fcm_token": "x"})
    assert resp.status_code == 422
