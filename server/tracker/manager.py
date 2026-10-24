"""Tracker Manager for orchestrating downloads across pairings and sources."""

import asyncio
import logging
import time

from server.notifier.base import BaseNotifier
from server.schemas import (
    DownloadState,
    EvaluatedDownloadItem,
    PushPayload,
    SamplePayload,
)
from server.throttler.push_throttler import PushThrottler
from server.tracker.download import InvalidStateTransitionError, TrackedDownload

logger = logging.getLogger("notifs.tracker")

TERMINAL_STATES = (DownloadState.COMPLETED, DownloadState.FAILED, DownloadState.ERASED)


class TrackerManager:
    """Manages all active download states and dispatches evaluated push payloads."""

    def __init__(
        self,
        notifier: BaseNotifier,
        cleanup_ttl_sec: float = 30.0,
        throttler: PushThrottler | None = None,
        idle_ttl_sec: float = 3600.0,
    ) -> None:
        self.notifier = notifier
        self.cleanup_ttl_sec = cleanup_ttl_sec
        # Non-terminal downloads whose PC went silent (lid closed, browser killed) would
        # otherwise stay in memory forever.
        self.idle_ttl_sec = idle_ttl_sec
        self.throttler = throttler
        # Server boot marker sent with every push (the throttler owns it when present)
        self.epoch = throttler.epoch if throttler else int(time.time() * 1000)
        # Map: (pairing_id, download_id) -> TrackedDownload
        self._downloads: dict[tuple[str, str], TrackedDownload] = {}
        # Map: pairing_id -> current seq number (used when no throttler configured)
        self._seq_map: dict[str, int] = {}
        # Guards tracker state only; never held across a network send
        self._lock = asyncio.Lock()

    def _next_seq(self, pairing_id: str) -> int:
        """Returns the next incrementing sequence number (no-throttler mode)."""
        seq = self._seq_map.get(pairing_id, 0) + 1
        self._seq_map[pairing_id] = seq
        return seq

    def get_seq(self, pairing_id: str) -> int:
        """Returns the current sequence counter for a pairing."""
        if self.throttler:
            return self.throttler.get_seq(pairing_id)
        return self._seq_map.get(pairing_id, 0)

    def _evaluate(self, key: tuple[str, str], src_item, now: float) -> EvaluatedDownloadItem:
        tracked = self._downloads.get(key)
        if tracked is not None:
            try:
                return tracked.update(src_item, timestamp=now)
            except InvalidStateTransitionError as err:
                # The source is the source of truth (e.g. the browser restarted a download from
                # byte 0). Rejecting the sample would 500 every retry and wedge the pairing.
                logger.warning("Resetting download %s after illegal transition: %s", key, err)

        tracked = TrackedDownload(src_item, timestamp=now)
        self._downloads[key] = tracked
        return tracked.to_evaluated()

    async def process_sample(
        self,
        sample: SamplePayload,
        target_token: str | None = None,
    ) -> PushPayload:
        """Ingests a SamplePayload, updates download states, and triggers notification."""
        async with self._lock:
            # Sample timestamps (source clock) drive speed; cleanup uses the server's clock.
            now = sample.timestamp.timestamp() if sample.timestamp else time.time()
            evaluated_list: list[EvaluatedDownloadItem] = []

            for src_item in sample.downloads:
                key = (sample.pairing_id, src_item.id)
                evaluated_list.append(self._evaluate(key, src_item, now))
                if evaluated_list[-1].state == DownloadState.ERASED:
                    self._downloads.pop(key, None)

            push_payload = PushPayload(
                seq=self.get_seq(sample.pairing_id) or 1,
                source=sample.source,
                pc_name=sample.pc_name,
                pairing_id=sample.pairing_id,
                downloads=evaluated_list,
            )
            if not self.throttler:
                push_payload.seq = self._next_seq(sample.pairing_id)
                push_payload.epoch = self.epoch

            self._cleanup_stale()

        # Send outside the lock so one slow FCM call cannot stall every other pairing.
        if self.throttler:
            await self.throttler.submit(push_payload, target_token=target_token)
        else:
            await self.notifier.notify(push_payload, target_token=target_token)

        return push_payload

    def _cleanup_stale(self) -> None:
        """Evicts finished downloads after cleanup_ttl_sec and silent ones after idle_ttl_sec."""
        now = time.monotonic()
        to_remove = [
            key
            for key, tracked in self._downloads.items()
            if (now - tracked.last_seen)
            > (self.cleanup_ttl_sec if tracked.state in TERMINAL_STATES else self.idle_ttl_sec)
        ]
        for key in to_remove:
            self._downloads.pop(key, None)

    def get_active_count(self, pairing_id: str | None = None) -> int:
        """Returns the number of active tracked downloads."""
        if pairing_id is None:
            return len(self._downloads)
        return sum(1 for (p_id, _) in self._downloads if p_id == pairing_id)

    async def forget_pairing(self, pairing_id: str) -> None:
        """Drops tracked downloads and push state for an unpaired session."""
        async with self._lock:
            for key in [k for k in self._downloads if k[0] == pairing_id]:
                del self._downloads[key]
            self._seq_map.pop(pairing_id, None)
        if self.throttler:
            await self.throttler.forget(pairing_id)

    async def close(self) -> None:
        """Closes throttler resources."""
        if self.throttler:
            await self.throttler.close()
