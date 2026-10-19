"""Pairing API router managing QR codes, claim validation, and device pairings."""

import contextlib
import logging
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from server.auth import PairingActorDep, PairingRole, StoreDep, hash_secret
from server.rate_limiter import (
    limit_by_ip,
    pairing_claim_limiter,
    pairing_create_limiter,
    pairing_manage_limiter,
)
from server.schemas import (
    PAIRING_CODE_PATTERN,
    ClaimPairingRequest,
    ClaimPairingResponse,
    CreatePairingRequest,
    CreatePairingResponse,
    PairingStatusResponse,
    RotateSecretResponse,
    UpdateTokenRequest,
    UpdateTokenResponse,
)

logger = logging.getLogger("notifs.api.pairings")

router = APIRouter(prefix="/v1/pairings", tags=["Pairings"])

PairingCodePath = Annotated[str, Path(pattern=PAIRING_CODE_PATTERN)]
ManageRateLimit = Depends(limit_by_ip(pairing_manage_limiter))

PAIRING_CODE_TTL_SEC = 300


def generate_pairing_code(length: int = 6) -> str:
    """Generates a secure 6-character uppercase alphanumeric claim code."""
    # Exclude ambiguous characters like 0, O, 1, I for readability
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(chars) for _ in range(length))


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.post(
    "",
    response_model=CreatePairingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_ip(pairing_create_limiter))],
)
async def create_pairing(
    payload: CreatePairingRequest,
    store: StoreDep,
) -> CreatePairingResponse:
    """Generates an ephemeral 6-character pairing code and bearer secret for the extension."""
    pairing_id = str(uuid.uuid4())
    code = generate_pairing_code(6)
    secret = secrets.token_urlsafe(32)

    record = await store.create_pairing(
        pairing_id=pairing_id,
        code=code,
        secret_hash=hash_secret(secret),
        pc_name=payload.pc_name,
        expires_in_sec=PAIRING_CODE_TTL_SEC,
    )

    return CreatePairingResponse(
        pairing_id=record.pairing_id,
        code=record.code,
        secret=secret,
        expires_at=record.expires_at,
    )


@router.post(
    "/{code}/claim",
    response_model=ClaimPairingResponse,
    dependencies=[Depends(limit_by_ip(pairing_claim_limiter))],
)
async def claim_pairing(
    code: PairingCodePath,
    payload: ClaimPairingRequest,
    store: StoreDep,
) -> ClaimPairingResponse:
    """Claims a pairing code for a phone and issues the phone its own bearer secret."""
    device_secret = secrets.token_urlsafe(32)
    record = await store.claim_pairing(code.upper(), payload.fcm_token, hash_secret(device_secret))

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, max attempts exceeded, or already claimed pairing code",
        )

    return ClaimPairingResponse(
        status="ok",
        pairing_id=record.pairing_id,
        pc_name=record.pc_name,
        device_secret=device_secret,
    )


@router.get("/{pairing_id}", response_model=PairingStatusResponse)
async def get_pairing_status(actor: PairingActorDep) -> PairingStatusResponse:
    """Returns the claim status of a pairing (extension or device secret)."""
    record = actor.record
    return PairingStatusResponse(
        pairing_id=record.pairing_id,
        is_claimed=record.is_claimed,
        pc_name=record.pc_name,
        created_at=record.created_at,
        claimed_at=record.claimed_at,
    )


@router.delete("/{pairing_id}", dependencies=[ManageRateLimit])
async def delete_pairing(
    actor: PairingActorDep,
    store: StoreDep,
    request: Request,
) -> dict:
    """Unpairs the session. Either side may unpair; the phone is told when the PC does it."""
    record = actor.record

    if actor.role == PairingRole.EXTENSION and record.fcm_token:
        notifier = getattr(request.app.state, "notifier", None)
        if notifier is not None:
            with contextlib.suppress(Exception):
                await notifier.send_unpair_event(record.fcm_token, record.pairing_id)

    await store.delete_pairing(record.pairing_id)

    tracker = getattr(request.app.state, "tracker_manager", None)
    if tracker is not None:
        await tracker.forget_pairing(record.pairing_id)

    logger.info("Pairing %s deleted by %s", record.pairing_id, actor.role)
    return {"status": "ok", "message": "Pairing deleted successfully"}


@router.post(
    "/{pairing_id}/token",
    response_model=UpdateTokenResponse,
    dependencies=[ManageRateLimit],
)
async def update_pairing_token(
    payload: UpdateTokenRequest,
    actor: PairingActorDep,
    store: StoreDep,
) -> UpdateTokenResponse:
    """Updates the FCM token. Only the phone may do this, so pushes cannot be redirected."""
    if actor.role != PairingRole.DEVICE:
        raise _forbidden("Only the paired device may update its FCM token")

    if not await store.update_fcm_token(actor.record.pairing_id, payload.fcm_token):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update device token",
        )

    return UpdateTokenResponse(status="ok", pairing_id=actor.record.pairing_id)


@router.post(
    "/{pairing_id}/rotate-secret",
    response_model=RotateSecretResponse,
    dependencies=[ManageRateLimit],
)
async def rotate_pairing_secret(
    actor: PairingActorDep,
    store: StoreDep,
) -> RotateSecretResponse:
    """Rotates the extension's bearer secret; the old one is rejected immediately."""
    if actor.role != PairingRole.EXTENSION:
        raise _forbidden("Only the extension may rotate its secret")

    new_secret = secrets.token_urlsafe(32)
    if not await store.rotate_secret(actor.record.pairing_id, hash_secret(new_secret)):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to rotate secret",
        )

    return RotateSecretResponse(
        status="ok",
        pairing_id=actor.record.pairing_id,
        new_secret=new_secret,
    )
