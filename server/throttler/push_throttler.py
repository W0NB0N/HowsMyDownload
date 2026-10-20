"""Push Throttler for rate-limiting download updates per pairing.

Enforces a rate limit of max one push per interval (default 2.0s), while allowing
state transitions (starting, downloading -> paused, completed, failed, or download added/removed)
to bypass the throttle immediately. Discarded interim progress updates are coalesced into the
single latest PushPayload, and strictly monotonic sequence numbers are assigned only upon
actual over-the-wire dispatch.

Sequence numbers live in memory and restart at 1 when the process restarts. Every payload
therefore carries `epoch` (the throttler's creation time in ms). The phone only compares seq
within one epoch and treats a new epoch as a fresh stream (see android SequenceGate.kt).
"""

import asyncio
import logging
import time

from server.notifier.base import BaseNotifier
from server.schemas import DownloadState, PushPayload

logger = logging.getLogger("notifs.throttler")


class PushThrottler:
    """Per-pairing rate limiter and strict sequence assigner for push notifications."""

    def __init__(
        self,
        notifier: BaseNotifier,
        min_interval_sec: float = 2.0,
        epoch: int | None = None,
    ) -> None:
        self.notifier = notifier
        self.min_interval_sec = min_interval_sec
        self.epoch = epoch if epoch is not None else int(time.time() * 1000)

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

        # Guards the dicts above; never held across a network send
        self._lock = asyncio.Lock()

        # pairing_id -> lock serializing that pairing's sends (keeps seq order on the wire)
        self._send_locks: dict[str, asyncio.Lock] = {}

    def _next_seq(self, pairing_id: str) -> int:
        """Returns the next incrementing sequence number for the pairing."""
        seq = self._seq_map.get(pairing_id, 0) + 1
        self._seq_map[pairing_id] = seq
        return seq

    def get_seq(self, pairing_id: str) -> int:
        """Returns the current sequence number for a pairing without incrementing."""
        return self._seq_map.get(pairing_id, 0)

    def _has_state_changed(self, pairing_id: str, payload: PushPayload) -> bool:
        """Detects if any download state represents a transition or download add/remove."""
        prev_states = self._last_known_states.get(pairing_id)
        if prev_states is None:
            # First push for this pairing is considered a state transition
            return True

        current_states = {dl.id: dl.state for dl in payload.downloads}

        # Check if set of download IDs changed (new download started or removed)
        if set(current_states.keys()) != set(prev_states.keys()):
            return True

        # Check if any individual download state changed (e.g. downloading -> paused/completed)
        for dl_id, current_state in current_states.items():
            if prev_states.get(dl_id) != current_state:
                return True

        return False

    def _prepare_dispatch(
        self, payload: PushPayload, target_token: str | None
    ) -> tuple[PushPayload, str | None]:
        """Claims the next seq and records dispatch state. Caller must hold self._lock."""
        pairing_id = payload.pairing_id

        # Cancel any pending delayed task for this pairing since we are pushing now
        existing_task = self._flush_tasks.pop(pairing_id, None)
        if existing_task and not existing_task.done():
            existing_task.cancel()
        self._pending_payloads.pop(pairing_id, None)

        # Monotonically assign sequence number ONLY upon actual dispatch
        payload.seq = self._next_seq(pairing_id)
        payload.epoch = self.epoch

        self._last_push_times[pairing_id] = time.time()
        self._last_known_states[pairing_id] = {dl.id: dl.state for dl in payload.downloads}
        return payload, target_token

    async def _send(self, payload: PushPayload, target_token: str | None) -> None:
        """Sends outside the state lock. A per-pairing lock keeps one pairing's pushes in seq
        order while other pairings proceed in parallel. asyncio.Lock is FIFO and callers
        enqueue here before yielding after _prepare_dispatch, so send order == seq order."""
        send_lock = self._send_locks.setdefault(payload.pairing_id, asyncio.Lock())
        async with send_lock:
            try:
                await self.notifier.notify(payload, target_token=target_token)
            except Exception as err:
                logger.error(
                    "[PushThrottler] Error during notification dispatch for %s: %s",
                    payload.pairing_id,
                    err,
                )

    async def _delayed_flush(self, pairing_id: str, delay: float) -> None:
        """Background coroutine that sleeps for the remaining throttle window then pushes."""
        try:
            await asyncio.sleep(delay)
            async with self._lock:
                self._flush_tasks.pop(pairing_id, None)
                pending = self._pending_payloads.pop(pairing_id, None)
                prepared = self._prepare_dispatch(*pending) if pending else None
        except asyncio.CancelledError:
            # Cancelled because a state change or a newer push bypassed the throttle
            return
        if prepared:
            await self._send(*prepared)

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
        prepared = None
        async with self._lock:
            pairing_id = payload.pairing_id
            time_since_last = time.time() - self._last_push_times.get(pairing_id, 0.0)

            if (
                immediate
                or self._has_state_changed(pairing_id, payload)
                or time_since_last >= self.min_interval_sec
            ):
                # State-change bypass, or the throttle window has elapsed
                prepared = self._prepare_dispatch(payload, target_token)
            else:
                # Within throttle window: keep only the newest interim sample
                self._pending_payloads[pairing_id] = (payload, target_token)
                if pairing_id not in self._flush_tasks or self._flush_tasks[pairing_id].done():
                    remaining_delay = max(0.01, self.min_interval_sec - time_since_last)
                    self._flush_tasks[pairing_id] = asyncio.create_task(
                        self._delayed_flush(pairing_id, remaining_delay)
                    )

        if prepared:
            await self._send(*prepared)

    async def flush(self, pairing_id: str | None = None) -> None:
        """Forces immediate dispatch of any buffered pending payloads."""
        prepared = []
        async with self._lock:
            pairings = [pairing_id] if pairing_id else list(self._pending_payloads.keys())
            for p_id in pairings:
                pending = self._pending_payloads.get(p_id)
                if pending:
                    prepared.append(self._prepare_dispatch(*pending))
        for item in prepared:
            await self._send(*item)

    async def forget(self, pairing_id: str) -> None:
        """Drops all throttle state for an unpaired session."""
        async with self._lock:
            task = self._flush_tasks.pop(pairing_id, None)
            if task and not task.done():
                task.cancel()
            self._pending_payloads.pop(pairing_id, None)
            self._last_push_times.pop(pairing_id, None)
            self._last_known_states.pop(pairing_id, None)
            self._seq_map.pop(pairing_id, None)
            self._send_locks.pop(pairing_id, None)

    async def close(self) -> None:
        """Cancels all active delayed flush tasks."""
        async with self._lock:
            for task in self._flush_tasks.values():
                if not task.done():
                    task.cancel()
            self._flush_tasks.clear()
            self._pending_payloads.clear()
