"""Composite Notifier multiplexing across multiple backend notifiers."""

import asyncio
from collections.abc import Sequence

from server.notifier.base import BaseNotifier
from server.schemas import PushPayload


class CompositeNotifier(BaseNotifier):
    """Dispatches a single PushPayload concurrently across multiple notifiers."""

    def __init__(self, notifiers: Sequence[BaseNotifier]) -> None:
        self.notifiers = list(notifiers)

    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        """Executes all child notifiers in parallel."""
        if not self.notifiers:
            return

        tasks = []
        for notifier in self.notifiers:
            # Check if notifier supports target_token or call directly
            try:
                tasks.append(notifier.notify(payload, target_token=target_token))
            except TypeError:
                tasks.append(notifier.notify(payload))

        await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def store(self):
        for notifier in self.notifiers:
            if hasattr(notifier, "store") and notifier.store is not None:
                return notifier.store
        return None

    @store.setter
    def store(self, value) -> None:
        for notifier in self.notifiers:
            if hasattr(notifier, "store"):
                notifier.store = value

    async def send_unpair_event(self, token: str, pairing_id: str) -> None:
        """Dispatches unpair event to all child notifiers that support it."""
        tasks = [
            notifier.send_unpair_event(token, pairing_id)
            for notifier in self.notifiers
            if hasattr(notifier, "send_unpair_event")
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
