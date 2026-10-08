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
