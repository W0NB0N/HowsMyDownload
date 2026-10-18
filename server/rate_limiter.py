"""In-memory sliding window rate limiter for Download Notifs endpoints."""

import time
from collections import defaultdict
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from server.auth import get_authenticated_pairing
from server.store.base import PairingRecord


class SlidingWindowRateLimiter:
    """Sliding window rate limiter tracking request timestamps per client/pairing key."""

    def __init__(self, max_requests: int = 10, window_sec: float = 1.0) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Determines if a request with the given key is within the rate limit."""
        now = time.monotonic()
        cutoff = now - self.window_sec

        timestamps = self._requests[key]
        valid_timestamps = [t for t in timestamps if t > cutoff]
        self._requests[key] = valid_timestamps

        if len(valid_timestamps) >= self.max_requests:
            return False

        valid_timestamps.append(now)
        return True

    def reset(self) -> None:
        """Clears all stored rate limit history (useful for tests)."""
        self._requests.clear()


# Global rate limiter instance for sample ingestion (10 requests per second burst)
sample_rate_limiter = SlidingWindowRateLimiter(max_requests=10, window_sec=1.0)


async def check_sample_rate_limit(
    request: Request,
    auth_record: Annotated[PairingRecord, Depends(get_authenticated_pairing)],
) -> None:
    """FastAPI dependency enforcing rate limits per pairing session."""
    key = auth_record.pairing_id
    if not sample_rate_limiter.is_allowed(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 10 sample requests per second.",
            headers={"Retry-After": "1"},
        )
