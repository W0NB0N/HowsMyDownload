"""Unit tests for FCM Token Invalidation, session cleanup, and Token Refresh endpoint."""

from unittest.mock import patch
import pytest
from firebase_admin import exceptions, messaging
from server.notifier.fcm import FCMNotifier
from server.schemas import DownloadState, EvaluatedDownloadItem, PushPayload
from server.store.base import PairingRecord, utc_now
from server.store.memory import InMemoryPairingStore


@pytest.mark.asyncio
async def test_fcm_unregistered_error_purges_pairing():
    store = InMemoryPairingStore()
    await store.create_pairing(
        pairing_id="pair-revoked-1",
        code="REVOK1",
        secret_hash="hash123",
        pc_name="PC",
    )
    await store.claim_pairing("REVOK1", "bad-token-123")

    notifier = FCMNotifier(cred_path=None, store=store)

    payload = PushPayload(
        seq=1,
        source="chrome",
        pc_name="PC",
        pairing_id="pair-revoked-1",
        downloads=[
            EvaluatedDownloadItem(
                id="d1",
                filename="ubuntu.iso",
                state=DownloadState.DOWNLOADING,
                bytes_downloaded=100,
            )
        ],
    )

    with (
        patch("firebase_admin._apps", True),
        patch("firebase_admin.messaging.send", side_effect=messaging.UnregisteredError("App uninstalled")),
    ):
        await notifier.notify(payload, target_token="bad-token-123")

    # The revoked pairing must be purged from the store
    assert await store.get_pairing("pair-revoked-1") is None


@pytest.mark.asyncio
async def test_fcm_invalid_argument_error_purges_pairing():
    store = InMemoryPairingStore()
    await store.create_pairing(
        pairing_id="pair-invalid-2",
        code="INVAL2",
        secret_hash="hash456",
        pc_name="PC",
    )
    await store.claim_pairing("INVAL2", "malformed-token")

    notifier = FCMNotifier(cred_path=None, store=store)

    payload = PushPayload(
        seq=1,
        source="chrome",
        pc_name="PC",
        pairing_id="pair-invalid-2",
        downloads=[],
    )

    with (
        patch("firebase_admin._apps", True),
        patch("firebase_admin.messaging.send", side_effect=exceptions.InvalidArgumentError("Invalid registration token")),
    ):
        await notifier.notify(payload, target_token="malformed-token")

    # The invalid pairing must be purged from the store
    assert await store.get_pairing("pair-invalid-2") is None


@pytest.mark.asyncio
async def test_token_refresh_endpoint(client):
    # 1. Create a pairing
    resp = client.post("/v1/pairings", json={"pc_name": "My-PC"})
    assert resp.status_code == 201
    pairing_data = resp.json()
    pairing_id = pairing_data["pairing_id"]
    code = pairing_data["code"]

    # 2. Token refresh before claim should fail (400)
    resp_bad = client.post(f"/v1/pairings/{pairing_id}/token", json={"fcm_token": "new-token-abc"})
    assert resp_bad.status_code == 400

    # 3. Claim pairing
    claim_resp = client.post(f"/v1/pairings/{code}/claim", json={"fcm_token": "original-token"})
    assert claim_resp.status_code == 200

    # 4. Token refresh for non-existent pairing should return 404
    resp_404 = client.post("/v1/pairings/non-existent-id/token", json={"fcm_token": "new-token-abc"})
    assert resp_404.status_code == 404

    # 5. Token refresh for claimed pairing should succeed
    resp_ok = client.post(f"/v1/pairings/{pairing_id}/token", json={"fcm_token": "rotated-fcm-token-999"})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["status"] == "ok"
    assert resp_ok.json()["pairing_id"] == pairing_id

    # 6. Verify in store that token updated
    store = client.app.state.pairing_store
    updated = await store.get_pairing(pairing_id)
    assert updated.fcm_token == "rotated-fcm-token-999"
