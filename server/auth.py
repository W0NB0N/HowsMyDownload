"""Authentication utilities and FastAPI dependencies for Bearer token validation."""

import hashlib
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.config import settings
from server.store.base import BasePairingStore, PairingRecord, utc_now

security = HTTPBearer(auto_error=False)


def hash_secret(secret: str) -> str:
    """Computes SHA-256 hash digest of a bearer secret token."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def get_store(request: Request) -> BasePairingStore:
    """Dependency extracting the BasePairingStore instance from app.state."""
    return request.app.state.pairing_store


StoreDep = Annotated[BasePairingStore, Depends(get_store)]
AuthDep = Annotated[HTTPAuthorizationCredentials | None, Depends(security)]


async def get_authenticated_pairing(
    request: Request,
    credentials: AuthDep,
    store: StoreDep,
) -> PairingRecord:
    """Validates the Bearer token against stored pairing hashes and returns the
    active PairingRecord.
    """
    if credentials is None:
        # Check if running in dev mode with fallback test token
        if not getattr(settings, "REQUIRE_AUTH", True) and settings.target_fcm_token:
            # Dev mock pairing
            return PairingRecord(
                pairing_id="dev-local-pairing",
                code="DEV001",
                secret_hash="dev-mock-hash",
                pc_name="Desktop-PC",
                fcm_token=settings.target_fcm_token,
                expires_at=utc_now() + timedelta(days=365),
                is_claimed=True,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <secret> header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    secret = credentials.credentials
    secret_hash = hash_secret(secret)
    record = await store.get_pairing_by_secret_hash(secret_hash)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return record
