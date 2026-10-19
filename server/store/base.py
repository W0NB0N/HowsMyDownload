"""Abstract base class and models for pairing storage."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class PairingRecord(BaseModel):
    """Database entity representing a device pairing session and credentials."""
    model_config = ConfigDict(extra="ignore")

    pairing_id: str = Field(..., description="Unique UUID for this pairing")
    code: str = Field(..., description="Short alphanumeric claim code (e.g. 6 chars)")
    secret_hash: str = Field(..., description="SHA-256 hash of the extension's bearer secret")
    device_secret_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of the phone's bearer secret (issued at claim time)",
    )
    pc_name: str = Field(default="Desktop-PC", description="Client hostname")
    fcm_token: str | None = Field(default=None, description="Paired mobile device FCM token")
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(...)
    claimed_at: datetime | None = None
    claim_attempts: int = Field(default=0, ge=0)
    is_claimed: bool = Field(default=False)

    @property
    def is_expired(self) -> bool:
        return utc_now() > self.expires_at

    @property
    def is_usable(self) -> bool:
        """Claimed pairings never expire; an unclaimed one is only valid until its code expires."""
        return self.is_claimed or not self.is_expired


MAX_CLAIM_ATTEMPTS = 5


class BasePairingStore(ABC):
    """Abstract interface for storing and querying device pairings."""

    @abstractmethod
    async def create_pairing(
        self,
        pairing_id: str,
        code: str,
        secret_hash: str,
        pc_name: str,
        expires_in_sec: int = 300,
    ) -> PairingRecord:
        """Stores a new pairing code record with an expiration window."""
        pass

    @abstractmethod
    async def get_pairing(self, pairing_id: str) -> PairingRecord | None:
        """Retrieves a pairing record by its pairing_id."""
        pass

    @abstractmethod
    async def get_pairing_by_code(self, code: str) -> PairingRecord | None:
        """Retrieves a pairing record by its ephemeral claim code."""
        pass

    @abstractmethod
    async def get_pairing_by_secret_hash(self, secret_hash: str) -> PairingRecord | None:
        """Retrieves a pairing record by the SHA-256 hash of its bearer secret."""
        pass

    @abstractmethod
    async def claim_pairing(
        self,
        code: str,
        fcm_token: str,
        device_secret_hash: str,
    ) -> PairingRecord | None:
        """Claims an unexpired, unclaimed code for a phone. Returns None on any failure.

        Every attempt against an existing code counts toward MAX_CLAIM_ATTEMPTS.
        """
        pass

    @abstractmethod
    async def delete_pairing(self, pairing_id: str) -> bool:
        """Deletes/unpairs an active pairing."""
        pass

    @abstractmethod
    async def update_fcm_token(self, pairing_id: str, fcm_token: str) -> bool:
        """Updates the registered FCM token for an existing pairing."""
        pass

    @abstractmethod
    async def rotate_secret(self, pairing_id: str, new_secret_hash: str) -> bool:
        """Rotates the bearer secret hash for an existing pairing."""
        pass
