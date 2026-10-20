"""CachedPairingStore: cuts remote reads without ever serving revoked credentials."""

import asyncio

import pytest

from server.auth import hash_secret
from server.store.base import MAX_CLAIM_ATTEMPTS, PairingRecord, apply_claim, utc_now
from server.store.cached import CachedPairingStore
from server.store.memory import InMemoryPairingStore

PID = "11111111-1111-4111-8111-111111111111"


class CountingStore(InMemoryPairingStore):
    """Memory store that counts reads and can delay writes (to simulate Firestore latency)."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.write_delay = 0.0

    async def get_pairing_by_secret_hash(self, secret_hash):
        self.reads += 1
        return await super().get_pairing_by_secret_hash(secret_hash)

    async def rotate_secret(self, pairing_id, new_secret_hash):
        await asyncio.sleep(self.write_delay)
        return await super().rotate_secret(pairing_id, new_secret_hash)


async def _setup():
    inner = CountingStore()
    store = CachedPairingStore(inner, ttl_sec=60)
    await store.create_pairing(PID, "ABCDEF", hash_secret("s1"), "PC")
    await store.claim_pairing("ABCDEF", "tok", hash_secret("dev"))
    return inner, store


@pytest.mark.asyncio
async def test_repeated_auth_hits_remote_once():
    inner, store = await _setup()
    for _ in range(10):
        assert await store.get_pairing_by_secret_hash(hash_secret("s1")) is not None
    assert inner.reads == 1


@pytest.mark.asyncio
async def test_misses_are_not_cached():
    inner, store = await _setup()
    for _ in range(3):
        assert await store.get_pairing_by_secret_hash(hash_secret("guess")) is None
    assert inner.reads == 3
    assert store._by_hash.keys() == set()


@pytest.mark.asyncio
async def test_rotation_revokes_old_secret_immediately():
    _, store = await _setup()
    await store.get_pairing_by_secret_hash(hash_secret("s1"))  # warm cache
    await store.rotate_secret(PID, hash_secret("s2"))
    assert await store.get_pairing_by_secret_hash(hash_secret("s1")) is None
    assert await store.get_pairing_by_secret_hash(hash_secret("s2")) is not None


@pytest.mark.asyncio
async def test_read_racing_a_slow_write_cannot_recache_old_secret():
    inner, store = await _setup()
    inner.write_delay = 0.05
    rotation = asyncio.create_task(store.rotate_secret(PID, hash_secret("s2")))
    await asyncio.sleep(0.01)
    # Arrives mid-write: the remote still has the old secret, so this re-caches it...
    assert await store.get_pairing_by_secret_hash(hash_secret("s1")) is not None
    await rotation
    # ...but the post-write invalidation evicts it
    assert await store.get_pairing_by_secret_hash(hash_secret("s1")) is None


@pytest.mark.asyncio
async def test_delete_and_token_update_invalidate():
    _, store = await _setup()
    await store.get_pairing(PID)
    await store.update_fcm_token(PID, "tok2")
    assert (await store.get_pairing(PID)).fcm_token == "tok2"
    await store.delete_pairing(PID)
    assert await store.get_pairing(PID) is None
    assert await store.get_pairing_by_secret_hash(hash_secret("s1")) is None


@pytest.mark.asyncio
async def test_claim_invalidates_cached_unclaimed_record():
    inner = CountingStore()
    store = CachedPairingStore(inner)
    await store.create_pairing(PID, "QRCODE", hash_secret("s1"), "PC")
    # Extension polls status while the QR is shown
    assert not (await store.get_pairing_by_secret_hash(hash_secret("s1"))).is_claimed
    await store.claim_pairing("QRCODE", "tok", hash_secret("dev"))
    assert (await store.get_pairing_by_secret_hash(hash_secret("s1"))).is_claimed


@pytest.mark.asyncio
async def test_entries_expire_after_ttl():
    inner = CountingStore()
    store = CachedPairingStore(inner, ttl_sec=0)
    await store.create_pairing(PID, "ABCDEF", hash_secret("s1"), "PC")
    await store.get_pairing_by_secret_hash(hash_secret("s1"))
    await store.get_pairing_by_secret_hash(hash_secret("s1"))
    assert inner.reads == 2


def _record(**overrides) -> PairingRecord:
    from datetime import timedelta

    base = dict(
        pairing_id=PID, code="ABCDEF", secret_hash="h", expires_at=utc_now() + timedelta(minutes=5)
    )
    return PairingRecord(**{**base, **overrides})


def test_apply_claim_rules():
    from datetime import timedelta

    ok = _record()
    assert apply_claim(ok, "tok", "dev") and ok.is_claimed and ok.claim_attempts == 1

    assert not apply_claim(_record(is_claimed=True), "tok", "dev")
    assert not apply_claim(_record(expires_at=utc_now() - timedelta(seconds=1)), "tok", "dev")

    locked = _record(claim_attempts=MAX_CLAIM_ATTEMPTS)
    assert not apply_claim(locked, "tok", "dev")
    assert locked.claim_attempts == MAX_CLAIM_ATTEMPTS + 1 and locked.fcm_token is None
