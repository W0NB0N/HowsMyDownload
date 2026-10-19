"""In-memory sliding window rate limiters for Download Notifs endpoints.

State is per process, which is correct only because the server runs a single Uvicorn worker
(see deploy/Dockerfile). Nginx applies a coarser per-IP limit in front of this.
"""

import math
import time
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from server.auth import get_authenticated_pairing
from server.store.base import PairingRecord


class SlidingWindowRateLimiter:
    """Allows at most `max_requests` per `window_sec` for each key."""

    def __init__(self, max_requests: int, window_sec: float, max_keys: int = 10_000) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self.max_keys = max_keys
        self._requests: dict[str, deque[float]] = {}

    def retry_after(self, key: str) -> float:
        """Records a hit for `key`. Returns 0 if allowed, else seconds until the next slot."""
        now = time.monotonic()
        cutoff = now - self.window_sec

        timestamps = self._requests.get(key)
        if timestamps is None:
            if len(self._requests) >= self.max_keys:
                self._evict_idle(cutoff)
            timestamps = self._requests[key] = deque()

        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        if len(timestamps) >= self.max_requests:
            return timestamps[0] + self.window_sec - now

        timestamps.append(now)
        return 0.0

    def is_allowed(self, key: str) -> bool:
        return self.retry_after(key) == 0.0

    def _evict_idle(self, cutoff: float) -> None:
        """Drops keys whose newest hit is outside the window, bounding memory under key churn."""
        for key in [k for k, ts in self._requests.items() if not ts or ts[-1] <= cutoff]:
            del self._requests[key]

    def reset(self) -> None:
        """Clears all stored rate limit history (useful for tests)."""
        self._requests.clear()


# Extension polls every 2s and adds a sample on state changes: 10 per 10s per pairing
# (1 req/s sustained) leaves headroom for bursts without allowing floods.
sample_rate_limiter = SlidingWindowRateLimiter(max_requests=10, window_sec=10.0)

# Unauthenticated / low-frequency pairing endpoints, keyed by client IP.
pairing_create_limiter = SlidingWindowRateLimiter(max_requests=10, window_sec=60.0)
pairing_claim_limiter = SlidingWindowRateLimiter(max_requests=10, window_sec=60.0)
pairing_manage_limiter = SlidingWindowRateLimiter(max_requests=30, window_sec=60.0)

ALL_LIMITERS = (
    sample_rate_limiter,
    pairing_create_limiter,
    pairing_claim_limiter,
    pairing_manage_limiter,
)


def _raise_if_limited(limiter: SlidingWindowRateLimiter, key: str) -> None:
    wait = limiter.retry_after(key)
    if wait > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Slow down and retry later.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )


def client_ip(request: Request) -> str:
    """Client address as resolved by Uvicorn's --proxy-headers (X-Forwarded-For from Nginx)."""
    return request.client.host if request.client else "unknown"


def limit_by_ip(
    limiter: SlidingWindowRateLimiter,
) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """Builds a FastAPI dependency enforcing `limiter` per client IP."""

    async def dependency(request: Request) -> None:
        _raise_if_limited(limiter, client_ip(request))

    return dependency


async def check_sample_rate_limit(
    auth_record: Annotated[PairingRecord, Depends(get_authenticated_pairing)],
) -> None:
    """FastAPI dependency enforcing the sample rate limit per pairing session."""
    _raise_if_limited(sample_rate_limiter, auth_record.pairing_id)
