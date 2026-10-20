"""Read-through cache in front of a remote pairing store.

Every sample (every 2s per active download) authenticates by secret hash. Against Firestore
that was one query per sample. Reads are cached for a short TTL. Every write made through this
wrapper invalidates the affected pairing, and since the server runs as a single process, all
writes go through it, so a revoked or rotated secret stops working immediately.
"""

import time

from server.store.base import BasePairingStore, PairingRecord


class CachedPairingStore(BasePairingStore):
    def __init__(
        self,
        inner: BasePairingStore,
        ttl_sec: float = 30.0,
        max_entries: int = 10_000,
    ) -> None:
        self.inner = inner
        self.ttl_sec = ttl_sec
        self.max_entries = max_entries
        # Positive results only: caching misses would let random guesses fill memory, and a
        # freshly created pairing must be visible immediately.
        self._by_hash: dict[str, tuple[float, PairingRecord]] = {}
        self._by_id: dict[str, tuple[float, PairingRecord]] = {}

    # --- cache helpers ---------------------------------------------------------------

    def _get(self, cache: dict[str, tuple[float, PairingRecord]], key: str) -> PairingRecord | None:
        entry = cache.get(key)
        if entry is None:
            return None
        expires, record = entry
        if time.monotonic() >= expires:
            del cache[key]
            return None
        return record

    def _put(self, record: PairingRecord) -> None:
        if len(self._by_hash) + len(self._by_id) >= self.max_entries:
            self._by_hash.clear()
            self._by_id.clear()
        expires = time.monotonic() + self.ttl_sec
        self._by_hash[record.secret_hash] = (expires, record)
        self._by_id[record.pairing_id] = (expires, record)

    def invalidate(self, pairing_id: str) -> None:
        entry = self._by_id.pop(pairing_id, None)
        if entry is not None:
            self._by_hash.pop(entry[1].secret_hash, None)
        for key in [k for k, (_, r) in self._by_hash.items() if r.pairing_id == pairing_id]:
            del self._by_hash[key]

    # --- reads -----------------------------------------------------------------------

    async def get_pairing(self, pairing_id: str) -> PairingRecord | None:
        record = self._get(self._by_id, pairing_id)
        if record is None:
            record = await self.inner.get_pairing(pairing_id)
            if record is not None:
                self._put(record)
        return record

    async def get_pairing_by_secret_hash(self, secret_hash: str) -> PairingRecord | None:
        record = self._get(self._by_hash, secret_hash)
        if record is None:
            record = await self.inner.get_pairing_by_secret_hash(secret_hash)
            if record is not None:
                self._put(record)
        return record

    async def get_pairing_by_code(self, code: str) -> PairingRecord | None:
        # Claim-time only; must see the latest attempt counter, so never cached
        return await self.inner.get_pairing_by_code(code)

    # --- writes ---------------------------------------------------------------------
    # Invalidate before AND after the write: a read racing the remote write could otherwise
    # re-cache the old record (e.g. keep a rotated-out secret valid for a full TTL).

    async def create_pairing(
        self,
        pairing_id: str,
        code: str,
        secret_hash: str,
        pc_name: str,
        expires_in_sec: int = 300,
    ) -> PairingRecord:
        return await self.inner.create_pairing(
            pairing_id, code, secret_hash, pc_name, expires_in_sec
        )

    async def claim_pairing(
        self,
        code: str,
        fcm_token: str,
        device_secret_hash: str,
    ) -> PairingRecord | None:
        record = await self.inner.claim_pairing(code, fcm_token, device_secret_hash)
        if record is not None:
            self.invalidate(record.pairing_id)
        return record

    async def delete_pairing(self, pairing_id: str) -> bool:
        self.invalidate(pairing_id)
        try:
            return await self.inner.delete_pairing(pairing_id)
        finally:
            self.invalidate(pairing_id)

    async def update_fcm_token(self, pairing_id: str, fcm_token: str) -> bool:
        self.invalidate(pairing_id)
        try:
            return await self.inner.update_fcm_token(pairing_id, fcm_token)
        finally:
            self.invalidate(pairing_id)

    async def rotate_secret(self, pairing_id: str, new_secret_hash: str) -> bool:
        self.invalidate(pairing_id)
        try:
            return await self.inner.rotate_secret(pairing_id, new_secret_hash)
        finally:
            self.invalidate(pairing_id)
