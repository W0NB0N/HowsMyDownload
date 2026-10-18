"""In-memory implementation of BasePairingStore for local dev and unit testing."""

import asyncio
from datetime import timedelta

from server.store.base import BasePairingStore, PairingRecord, utc_now


class InMemoryPairingStore(BasePairingStore):
    """Thread-safe in-memory store for pairings."""

    def __init__(self) -> None:
        self._by_id: dict[str, PairingRecord] = {}
        self._by_code: dict[str, str] = {}
        self._by_secret_hash: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create_pairing(
        self,
        pairing_id: str,
        code: str,
        secret_hash: str,
        pc_name: str,
        expires_in_sec: int = 300,
    ) -> PairingRecord:
        async with self._lock:
            now = utc_now()
            record = PairingRecord(
                pairing_id=pairing_id,
                code=code,
                secret_hash=secret_hash,
                pc_name=pc_name,
                created_at=now,
                expires_at=now + timedelta(seconds=expires_in_sec),
                claim_attempts=0,
                is_claimed=False,
            )
            self._by_id[pairing_id] = record
            self._by_code[code.upper()] = pairing_id
            self._by_secret_hash[secret_hash] = pairing_id
            return record

    async def get_pairing(self, pairing_id: str) -> PairingRecord | None:
        async with self._lock:
            return self._by_id.get(pairing_id)

    async def get_pairing_by_code(self, code: str) -> PairingRecord | None:
        async with self._lock:
            p_id = self._by_code.get(code.upper())
            if not p_id:
                return None
            return self._by_id.get(p_id)

    async def get_pairing_by_secret_hash(self, secret_hash: str) -> PairingRecord | None:
        async with self._lock:
            p_id = self._by_secret_hash.get(secret_hash)
            if not p_id:
                return None
            return self._by_id.get(p_id)

    async def claim_pairing(self, code: str, fcm_token: str) -> PairingRecord | None:
        async with self._lock:
            p_id = self._by_code.get(code.upper())
            if not p_id:
                return None

            record = self._by_id.get(p_id)
            if not record:
                return None

            # Check expiration and attempts limit (max 5)
            if record.is_expired:
                return None

            if record.claim_attempts >= 5:
                return None

            record.claim_attempts += 1

            if record.is_claimed:
                return None

            # Mark claimed
            record.fcm_token = fcm_token
            record.is_claimed = True
            record.claimed_at = utc_now()
            return record

    async def delete_pairing(self, pairing_id: str) -> bool:
        async with self._lock:
            record = self._by_id.pop(pairing_id, None)
            if not record:
                return False
            self._by_code.pop(record.code.upper(), None)
            self._by_secret_hash.pop(record.secret_hash, None)
            return True

    async def update_fcm_token(self, pairing_id: str, fcm_token: str) -> bool:
        async with self._lock:
            record = self._by_id.get(pairing_id)
            if not record:
                return False
            record.fcm_token = fcm_token
            return True

    async def rotate_secret(self, pairing_id: str, new_secret_hash: str) -> bool:
        async with self._lock:
            record = self._by_id.get(pairing_id)
            if not record:
                return False
            self._by_secret_hash.pop(record.secret_hash, None)
            record.secret_hash = new_secret_hash
            self._by_secret_hash[new_secret_hash] = pairing_id
            return True
