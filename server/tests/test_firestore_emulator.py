"""FirestorePairingStore against the real Firestore emulator (runs in CI).

Skipped unless FIRESTORE_EMULATOR_HOST is set. To run locally (needs Java 11+):
    npx -y firebase-tools@13.35.1 emulators:exec --only firestore --project demo-hmd
        --config tools/firestore-emulator/firebase.json
        "cd server && pytest tests/test_firestore_emulator.py -o addopts="
(13.29.x is broken: it looks for templates under lib/. On Windows the emulator's java
process can outlive the command; stop whatever holds port 8085 afterwards.)
"""

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="Firestore emulator not running"
)


@pytest.fixture
def store():
    from google.cloud import firestore

    from server.store.firestore import FirestorePairingStore

    # demo-* projects need no credentials when talking to the emulator
    client = firestore.Client(project="demo-hmd")
    return FirestorePairingStore(collection_name=f"test-{uuid.uuid4().hex[:8]}", client=client)


async def _create(store, code="EMU123", expires_in_sec=300):
    pairing_id = str(uuid.uuid4())
    await store.create_pairing(pairing_id, code, "secret-hash", "PC", expires_in_sec)
    return pairing_id


@pytest.mark.asyncio
async def test_create_claim_and_lookup(store):
    pid = await _create(store)
    claimed = await store.claim_pairing("emu123", "fcm-token", "device-hash")
    assert claimed is not None and claimed.is_claimed
    assert claimed.device_secret_hash == "device-hash"

    by_hash = await store.get_pairing_by_secret_hash("secret-hash")
    assert by_hash.pairing_id == pid and by_hash.fcm_token == "fcm-token"


@pytest.mark.asyncio
async def test_purge_at_is_set_until_claimed(store):
    pid = await _create(store)
    doc_ref = store._db.collection(store.collection_name).document(pid)
    assert doc_ref.get().to_dict()["purge_at"] is not None

    await store.claim_pairing("EMU123", "tok", "dev")
    assert "purge_at" not in doc_ref.get().to_dict()


@pytest.mark.asyncio
async def test_concurrent_claims_only_one_wins(store):
    await _create(store)
    results = await asyncio.gather(
        *[store.claim_pairing("EMU123", f"tok-{i}", f"dev-{i}") for i in range(5)]
    )
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    final = await store.get_pairing_by_secret_hash("secret-hash")
    assert final.fcm_token == winners[0].fcm_token
    assert final.claim_attempts == 5  # every attempt counted, none lost


@pytest.mark.asyncio
async def test_attempt_limit_and_expiry(store):
    await _create(store, code="LOCKED")
    await _create(store, code="EXPIRD", expires_in_sec=-1)
    assert await store.claim_pairing("EXPIRD", "tok", "dev") is None

    record = await store.get_pairing_by_code("LOCKED")
    store._db.collection(store.collection_name).document(record.pairing_id).update(
        {"claim_attempts": 5}
    )
    assert await store.claim_pairing("LOCKED", "tok", "dev") is None


@pytest.mark.asyncio
async def test_rotate_update_delete(store):
    pid = await _create(store)
    await store.claim_pairing("EMU123", "tok", "dev")
    assert await store.rotate_secret(pid, "new-hash")
    assert await store.get_pairing_by_secret_hash("secret-hash") is None
    assert await store.update_fcm_token(pid, "tok2")
    assert (await store.get_pairing(pid)).fcm_token == "tok2"
    assert await store.delete_pairing(pid)
    assert await store.get_pairing(pid) is None
