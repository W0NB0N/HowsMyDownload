"""Tracker Manager for orchestrating downloads across pairings and sources."""

import asyncio
import time

from server.notifier.base import BaseNotifier
from server.schemas import (
    DownloadState,
    EvaluatedDownloadItem,
    PushPayload,
    SamplePayload,
)
from server.tracker.download import TrackedDownload


class TrackerManager:
    """Manages all active download states and dispatches evaluated push payloads."""

    def __init__(self, notifier: BaseNotifier, cleanup_ttl_sec: float = 30.0) -> None:
        self.notifier = notifier
        self.cleanup_ttl_sec = cleanup_ttl_sec
        # Map: (pairing_id, download_id) -> TrackedDownload
        self._downloads: dict[tuple[str, str], TrackedDownload] = {}
        # Map: pairing_id -> current seq number
        self._seq_map: dict[str, int] = {}
        # Lock for thread/async safety
        self._lock = asyncio.Lock()

    def _next_seq(self, pairing_id: str) -> int:
        """Returns the next incrementing sequence number for the pairing."""
        seq = self._seq_map.get(pairing_id, 0) + 1
        self._seq_map[pairing_id] = seq
        return seq

    async def process_sample(
        self,
        sample: SamplePayload,
        target_token: str | None = None,
    ) -> PushPayload:
        """Ingests a SamplePayload, updates download states, and triggers notification."""
        async with self._lock:
            now = sample.timestamp.timestamp() if sample.timestamp else time.time()
            evaluated_list: list[EvaluatedDownloadItem] = []

            for src_item in sample.downloads:
                key = (sample.pairing_id, src_item.id)
                tracked = self._downloads.get(key)

                if tracked is None:
                    # New download
                    tracked = TrackedDownload(src_item)
                    self._downloads[key] = tracked
                    evaluated = tracked.to_evaluated()
                else:
                    # Update existing download
                    evaluated = tracked.update(src_item, timestamp=now)

                evaluated_list.append(evaluated)

                # If download reached terminal state (erased), schedule cleanup
                if tracked.state == DownloadState.ERASED:
                    self._downloads.pop(key, None)

            seq = self._next_seq(sample.pairing_id)

            push_payload = PushPayload(
                seq=seq,
                source=sample.source,
                pc_name=sample.pc_name,
                pairing_id=sample.pairing_id,
                downloads=evaluated_list,
            )

            # Dispatch to notifier backend
            await self.notifier.notify(push_payload, target_token=target_token)

            # Run periodic cleanup
            self._cleanup_stale(now)

            return push_payload

    def _cleanup_stale(self, now: float) -> None:
        """Removes old completed or failed downloads that haven't updated in cleanup_ttl_sec."""
        terminal_states = (DownloadState.COMPLETED, DownloadState.FAILED, DownloadState.ERASED)
        to_remove = [
            key
            for key, tracked in self._downloads.items()
            if tracked.state in terminal_states
            and (now - tracked.last_updated_at) > self.cleanup_ttl_sec
        ]

        for key in to_remove:
            self._downloads.pop(key, None)

    def get_active_count(self, pairing_id: str | None = None) -> int:
        """Returns the number of active tracked downloads."""
        if pairing_id is None:
            return len(self._downloads)
        return sum(1 for (p_id, _) in self._downloads if p_id == pairing_id)
