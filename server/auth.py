"""Authentication utilities and FastAPI dependencies for Bearer token validation.

Two credentials exist per pairing, both 256-bit random tokens stored only as SHA-256 hashes
(a slow KDF adds nothing for high-entropy secrets):
- the extension secret, issued at POST /v1/pairings, authorizes samples and pairing management;
- the device secret, issued to the phone at claim time, authorizes token refresh and unpair.
"""

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.schemas import PAIRING_ID_PATTERN
from server.store.base import BasePairingStore, PairingRecord

security = HTTPBearer(auto_error=False)

PairingIdPath = Annotated[str, Path(pattern=PAIRING_ID_PATTERN)]


def hash_secret(secret: str) -> str:
    """Computes SHA-256 hash digest of a bearer secret token."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_matches(secret: str, expected_hash: str | None) -> bool:
    """Constant-time comparison of a presented secret against a stored hash."""
    if not expected_hash:
        return False
    return hmac.compare_digest(hash_secret(secret), expected_hash)


def get_store(request: Request) -> BasePairingStore:
    """Dependency extracting the BasePairingStore instance from app.state."""
    return request.app.state.pairing_store


StoreDep = Annotated[BasePairingStore, Depends(get_store)]
AuthDep = Annotated[HTTPAuthorizationCredentials | None, Depends(security)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_authenticated_pairing(credentials: AuthDep, store: StoreDep) -> PairingRecord:
    """Resolves the pairing owning the presented extension secret."""
    if credentials is None:
        raise _unauthorized("Missing Authorization: Bearer <secret> header")

    record = await store.get_pairing_by_secret_hash(hash_secret(credentials.credentials))
    if record is None or not record.is_usable:
        raise _unauthorized("Invalid or expired bearer token")
    return record


class PairingRole(StrEnum):
    EXTENSION = "extension"
    DEVICE = "device"


@dataclass(frozen=True)
class PairingActor:
    record: PairingRecord
    role: PairingRole


async def get_pairing_actor(
    pairing_id: PairingIdPath,
    credentials: AuthDep,
    store: StoreDep,
) -> PairingActor:
    """Authorizes a request against the pairing named in the path.

    Accepts the extension secret or the device secret. Unknown pairings and wrong secrets
    both return 401 so the endpoint cannot be used to probe which pairing IDs exist.
    """
    if credentials is None:
        raise _unauthorized("Missing Authorization: Bearer <secret> header")

    record = await store.get_pairing(pairing_id)
    if record is not None and record.is_usable:
        if secret_matches(credentials.credentials, record.secret_hash):
            return PairingActor(record=record, role=PairingRole.EXTENSION)
        if secret_matches(credentials.credentials, record.device_secret_hash):
            return PairingActor(record=record, role=PairingRole.DEVICE)

    raise _unauthorized("Invalid credentials for this pairing")


PairingActorDep = Annotated[PairingActor, Depends(get_pairing_actor)]
