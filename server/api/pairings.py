"""Pairing API router managing QR codes, claim validation, and device pairings."""

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from server.auth import StoreDep, get_authenticated_pairing, hash_secret, security
from server.schemas import (
    ClaimPairingRequest,
    ClaimPairingResponse,
    CreatePairingRequest,
    CreatePairingResponse,
    PairingStatusResponse,
    UpdateTokenRequest,
    UpdateTokenResponse,
)
from server.store.base import PairingRecord

router = APIRouter(prefix="/v1/pairings", tags=["Pairings"])


def generate_pairing_code(length: int = 6) -> str:
    """Generates a secure 6-character uppercase alphanumeric claim code."""
    # Exclude ambiguous characters like 0, O, 1, I for readability
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(chars) for _ in range(length))


@router.post("", response_model=CreatePairingResponse, status_code=status.HTTP_201_CREATED)
async def create_pairing(
    payload: CreatePairingRequest,
    store: StoreDep,
) -> CreatePairingResponse:
    """Generates an ephemeral 6-digit pairing code and bearer secret for the extension."""
    pairing_id = str(uuid.uuid4())
    code = generate_pairing_code(6)
    secret = secrets.token_urlsafe(32)
    secret_hash = hash_secret(secret)

    record = await store.create_pairing(
        pairing_id=pairing_id,
        code=code,
        secret_hash=secret_hash,
        pc_name=payload.pc_name,
        expires_in_sec=300,  # 5 minutes
    )

    return CreatePairingResponse(
        pairing_id=record.pairing_id,
        code=record.code,
        secret=secret,
        expires_at=record.expires_at,
    )


@router.post("/{code}/claim", response_model=ClaimPairingResponse)
async def claim_pairing(
    code: str,
    payload: ClaimPairingRequest,
    store: StoreDep,
) -> ClaimPairingResponse:
    """Claims an ephemeral pairing code with the mobile device's FCM token."""
    clean_code = code.strip().upper()
    record = await store.claim_pairing(clean_code, payload.fcm_token)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, max attempts exceeded, or already claimed pairing code",
        )

    return ClaimPairingResponse(
        status="ok",
        pairing_id=record.pairing_id,
        pc_name=record.pc_name,
    )


@router.get("/{pairing_id}", response_model=PairingStatusResponse)
async def get_pairing_status(
    pairing_id: str,
    auth_record: Annotated[PairingRecord, Depends(get_authenticated_pairing)],
) -> PairingStatusResponse:
    """Returns the current claim status of a pairing (requires Bearer token)."""
    if auth_record.pairing_id != pairing_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized for this pairing ID",
        )

    return PairingStatusResponse(
        pairing_id=auth_record.pairing_id,
        is_claimed=auth_record.is_claimed,
        pc_name=auth_record.pc_name,
        created_at=auth_record.created_at,
        claimed_at=auth_record.claimed_at,
    )


@router.delete("/{pairing_id}")
async def delete_pairing(
    pairing_id: str,
    store: StoreDep,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> dict:
    """Unpairs/deletes the pairing session (supports Bearer token or direct unpair)."""
    record = await store.get_pairing(pairing_id)

    if credentials is not None:
        secret_hash = hash_secret(credentials.credentials)
        auth_rec = await store.get_pairing_by_secret_hash(secret_hash)
        if auth_rec and auth_rec.pairing_id != pairing_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized for this pairing ID",
            )
        record = record or auth_rec

    # If the pairing was claimed by a phone, push unpair event via FCM
    if record and record.fcm_token:
        tracker = getattr(request.app.state, "tracker_manager", None)
        if tracker and hasattr(tracker, "notifier"):
            import contextlib
            with contextlib.suppress(Exception):
                await tracker.notifier.send_unpair_event(record.fcm_token, pairing_id)

    await store.delete_pairing(pairing_id)
    return {"status": "ok", "message": "Pairing deleted successfully"}


@router.post("/{pairing_id}/token", response_model=UpdateTokenResponse)
async def update_pairing_token(
    pairing_id: str,
    payload: UpdateTokenRequest,
    store: StoreDep,
) -> UpdateTokenResponse:
    """Updates the FCM device registration token for a claimed pairing."""
    record = await store.get_pairing(pairing_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pairing not found",
        )

    if not record.is_claimed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pairing is not claimed yet",
        )

    success = await store.update_fcm_token(pairing_id, payload.fcm_token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update device token",
        )

    return UpdateTokenResponse(status="ok", pairing_id=pairing_id)
