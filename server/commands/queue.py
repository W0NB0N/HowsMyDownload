"""In-memory queue of phone-issued download commands awaiting pickup by the extension.

The extension has no push channel, so it collects commands from the `/v1/samples` response
while a transfer is active and from `GET /v1/pairings/{id}/commands` while downloads are
paused or recently failed. Delivery is at-most-once: a command is removed when handed over.

State is per process (single Uvicorn worker, like the tracker and throttler). A restart drops
pending commands; the phone simply sees no change and can tap again.
"""

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from server.schemas import CommandAction, DownloadCommand

DEFAULT_TTL_SEC = 75.0
MAX_PENDING_PER_PAIRING = 20


@dataclass
class _Entry:
    command: DownloadCommand
    expires_at: float  # time.monotonic()


class CommandQueue:
    """Per-pairing pending commands with expiry and last-seen tracking for the extension.

    Every method is synchronous and never awaits, so each call is atomic on the event loop.
    """

    def __init__(
        self,
        ttl_sec: float = DEFAULT_TTL_SEC,
        max_per_pairing: int = MAX_PENDING_PER_PAIRING,
    ) -> None:
        self.ttl_sec = ttl_sec
        self.max_per_pairing = max_per_pairing
        # pairing_id -> download_id -> entry. One pending command per download: a newer tap
        # (pause, then resume before the PC picked it up) supersedes the older one.
        self._pending: dict[str, OrderedDict[str, _Entry]] = {}
        # pairing_id -> time.monotonic() of the extension's last pickup
        self._last_seen: dict[str, float] = {}

    def enqueue(
        self, pairing_id: str, download_id: str, action: CommandAction
    ) -> DownloadCommand:
        """Queues a command. An identical pending command is returned as-is (double taps)."""
        now = time.monotonic()
        pending = self._pending.setdefault(pairing_id, OrderedDict())

        existing = pending.get(download_id)
        if existing is not None and existing.expires_at > now and existing.command.action == action:
            return existing.command

        command = DownloadCommand(
            command_id=uuid.uuid4().hex,
            download_id=download_id,
            action=action,
        )
        pending.pop(download_id, None)
        pending[download_id] = _Entry(command=command, expires_at=now + self.ttl_sec)
        while len(pending) > self.max_per_pairing:
            pending.popitem(last=False)
        return command

    def drain(self, pairing_id: str) -> list[DownloadCommand]:
        """Hands over (and removes) every live command, marking the extension as seen.

        Expired commands stay put for `pop_expired` so the phone can be told about them.
        """
        now = time.monotonic()
        self._last_seen[pairing_id] = now
        pending = self._pending.get(pairing_id)
        if not pending:
            return []
        live = [download_id for download_id, e in pending.items() if e.expires_at > now]
        commands = [pending.pop(download_id).command for download_id in live]
        if not pending:
            del self._pending[pairing_id]
        return commands

    def pop_expired(self) -> list[tuple[str, DownloadCommand]]:
        """Removes and returns every command the extension failed to collect in time."""
        now = time.monotonic()
        expired: list[tuple[str, DownloadCommand]] = []
        for pairing_id in list(self._pending):
            pending = self._pending[pairing_id]
            for download_id in [d for d, e in pending.items() if e.expires_at <= now]:
                expired.append((pairing_id, pending.pop(download_id).command))
            if not pending:
                del self._pending[pairing_id]
        return expired

    def seconds_since_seen(self, pairing_id: str) -> int | None:
        """Seconds since the extension last collected commands, or None if never."""
        seen = self._last_seen.get(pairing_id)
        return None if seen is None else int(time.monotonic() - seen)

    def pending_count(self, pairing_id: str) -> int:
        return len(self._pending.get(pairing_id, ()))

    def forget(self, pairing_id: str) -> None:
        """Drops everything for an unpaired session."""
        self._pending.pop(pairing_id, None)
        self._last_seen.pop(pairing_id, None)
