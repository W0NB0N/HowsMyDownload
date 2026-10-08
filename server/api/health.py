"""Health check API router."""

from fastapi import APIRouter
from server.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Returns the server health and version status."""
    return HealthResponse()
