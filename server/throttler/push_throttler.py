"""Push Throttler for rate-limiting download updates per pairing.

Enforces a rate limit of max one push per interval (default 2.0s), while allowing
state transitions (starting, downloading -> paused, completed, failed, or download added/removed)
to bypass the throttle immediately. Discarded interim progress updates are coalesced into the
single latest PushPayload, and strictly monotonic sequence numbers are assigned only upon
actual over-the-wire dispatch.
"""

import asyncio
import logging
import time

from server.notifier.base import BaseNotifier
from server.schemas import DownloadState, PushPayload

logger = logging.getLogger("notifs.throttler")


class PushThrottler:
    """Per-pairing rate limiter and strict sequence assigner for push notifications."""

    def __init__(self, notifier: BaseNotifier, min_interval_sec: float = 2.0) -> None:
        self.notifier = notifier
        self.min_interval_sec = min_interval_sec

        # pairing_id -> timestamp of last dispatched push
        self._last_push_times: dict[str, float] = {}

        # pairing_id -> dict[download_id, DownloadState]
        self._last_known_states: dict[str, dict[str, DownloadState]] = {}

        # pairing_id -> (PushPayload, target_token)
        self._pending_payloads: dict[str, tuple[PushPayload, str | None]] = {}

        # pairing_id -> asyncio.Task for delayed flush
        self._flush_tasks: dict[str, asyncio.Task] = {}

        # pairing_id -> monotonic sequence number counter
        self._seq_map: dict[str, int] = {}

        # Async lock for thread/coroutine safety
        self._lock = asyncio.Lock()

    def _next_seq(self, pairing_id: str) -> int:
        """Returns the next incrementing sequence number for the pairing."""
        seq = self._seq_map.get(pairing_id, 0) + 1
        self._seq_map[pairing_id] = seq
        return seq

    def get_seq(self, pairing_id: str) -> int:
        """Returns the current sequence number for a pairing without incrementing."""
        return self._seq_map.get(pairing_id, 0)

    def _has_state_changed(self, pairing_id: str, payload: PushPayload) -> bool:
        """Detects if any download state represents a state transition or download addition/removal."""
        prev_states = self._last_known_states.get(pairing_id)
        if prev_states is None:
            # First push for this pairing is considered a state transition
            return True

        current_states = {dl.id: dl.state for dl in payload.downloads}

        # Check if set of download IDs changed (new download started or removed)
        if set(current_states.keys()) != set(prev_states.keys()):
            return True

        # Check if any individual download state changed (e.g. downloading -> paused/completed/failed)
        for dl_id, current_state in current_states.items():
            if prev_states.get(dl_id) != current_state:
                return True

        return False

    async def _dispatch_now(self, payload: PushPayload, target_token: str | None) -> None:
        """Assigns strict sequence number upon actual over-the-wire dispatch and sends."""
        pairing_id = payload.pairing_id

        # Cancel any pending delayed task for this pairing since we are pushing now
        existing_task = self._flush_tasks.pop(pairing_id, None)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        self._pending_payloads.pop(pairing_id, None)

        # Monotonically assign sequence number ONLY upon actual dispatch
        payload.seq = self._next_seq(pairing_id)

        # Record dispatch timestamp and latest states
        self._last_push_times[pairing_id] = time.time()
        self._last_known_states[pairing_id] = {dl.id: dl.state for dl in payload.downloads}

        try:
            await self.notifier.notify(payload, target_token=target_token)
        except Exception as err:
            logger.error(
                "[PushThrottler] Error during notification dispatch for %s: %s",
                pairing_id,
                err,
            )

    async def _delayed_flush(self, pairing_id: str, delay: float) -> None:
        """Background coroutine that sleeps for the remaining throttle window then pushes."""
        try:
            await asyncio.sleep(delay)
            async with self._lock:
                pending = self._pending_payloads.pop(pairing_id, None)
                self._flush_tasks.pop(pairing_id, None)
                if pending:
                    payload, token = pending
                    await self._dispatch_now(payload, token)
        except asyncio.CancelledError:
            # Task was cancelled because a state change or new push bypassed throttle
            pass

    async def submit(
        self,
        payload: PushPayload,
        target_token: str | None = None,
        immediate: bool = False,
    ) -> None:
        """Submits a PushPayload for rate-limited dispatch.

        If immediate=True or download states have changed (starting, downloading -> paused,
        completed, failed, or download added/removed), bypasses the throttle timer and dispatches
        immediately. Otherwise, coalesces the latest payload into the throttle window.
        """
        async with self._lock:
            pairing_id = payload.pairing_id
            now = time.time()
            last_push = self._last_push_times.get(pairing_id, 0.0)
            time_since_last = now - last_push

            is_state_change = immediate or self._has_state_changed(pairing_id, payload)

            if is_state_change:
                # State-Change Bypass: state changes require immediate alert delivery
                await self._dispatch_now(payload, target_token)
                return

            if time_since_last >= self.min_interval_sec:
                # Rate limit window has elapsed: dispatch immediately
                await self._dispatch_now(payload, target_token)
                return

            # Within throttle window: queue coalescing (overwriting previous interim progress sample)
            self._pending_payloads[pairing_id] = (payload, target_token)

            # Ensure a background task is scheduled to flush when the window expires
            if pairing_id not in self._flush_tasks or self._flush_tasks[pairing_id].done():
                remaining_delay = max(0.01, self.min_interval_sec - time_since_last)
                self._flush_tasks[pairing_id] = asyncio.create_task(
                    self._delayed_flush(pairing_id, remaining_delay)
                )

    async def flush(self, pairing_id: str | None = None) -> None:
        """Forces immediate dispatch of any buffered pending payloads."""
        async with self._lock:
            pairings = [pairing_id] if pairing_id else list(self._pending_payloads.keys())
            for p_id in pairings:
                task = self._flush_tasks.pop(p_id, None)
                if task and not task.done():
                    task.cancel()

                pending = self._pending_payloads.pop(p_id, None)
                if pending:
                    payload, token = pending
                    await self._dispatch_now(payload, token)

    async def close(self) -> None:
        """Cancels all active delayed flush tasks."""
        async with self._lock:
            for task in self._flush_tasks.values():
                if not task.done():
                    task.cancel()
            self._flush_tasks.clear()
            self._pending_payloads.clear()
