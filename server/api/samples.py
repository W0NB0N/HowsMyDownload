"""Sample ingestion API router."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from server.schemas import SamplePayload, SampleResponse
from server.tracker.manager import TrackerManager

router = APIRouter(prefix="/v1", tags=["Samples"])


def get_tracker(request: Request) -> TrackerManager:
    """Dependency that extracts the TrackerManager instance from app state."""
    return request.app.state.tracker_manager


TrackerDep = Annotated[TrackerManager, Depends(get_tracker)]


@router.post("/samples", response_model=SampleResponse)
async def receive_sample(
    payload: SamplePayload,
    tracker: TrackerDep,
) -> SampleResponse:
    """Ingests a download sample batch, computes metrics, and dispatches to notifier."""
    push_payload = await tracker.process_sample(payload)
    return SampleResponse(
        status="ok",
        processed=len(push_payload.downloads),
        pairing_id=payload.pairing_id,
    )
