"""Sample ingestion API router with Bearer token authentication."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from server.auth import get_authenticated_pairing
from server.rate_limiter import check_sample_rate_limit
from server.schemas import SamplePayload, SampleResponse
from server.store.base import PairingRecord
from server.tracker.manager import TrackerManager

router = APIRouter(prefix="/v1", tags=["Samples"])


def get_tracker(request: Request) -> TrackerManager:
    """Dependency that extracts the TrackerManager instance from app state."""
    return request.app.state.tracker_manager


TrackerDep = Annotated[TrackerManager, Depends(get_tracker)]
AuthPairingDep = Annotated[PairingRecord, Depends(get_authenticated_pairing)]


@router.post(
    "/samples",
    response_model=SampleResponse,
    dependencies=[Depends(check_sample_rate_limit)],
)
async def receive_sample(
    payload: SamplePayload,
    tracker: TrackerDep,
    auth_record: AuthPairingDep,
    request: Request,
) -> SampleResponse:
    """Ingests a download sample batch, computes metrics, and dispatches to notifier."""
    # Ensure pairing_id matches the authenticated pairing
    payload.pairing_id = auth_record.pairing_id
    payload.pc_name = auth_record.pc_name or payload.pc_name

    push_payload = await tracker.process_sample(
        payload,
        target_token=auth_record.fcm_token,
    )

    # While a transfer is active the extension samples every 2s, so phone commands ride back
    # on the response instead of costing a separate poll. Drained only after the sample was
    # processed: a request that fails above leaves the commands queued.
    queue = getattr(request.app.state, "command_queue", None)
    commands = queue.drain(auth_record.pairing_id) if queue is not None else []

    return SampleResponse(
        status="ok",
        processed=len(push_payload.downloads),
        pairing_id=payload.pairing_id,
        commands=commands,
    )
