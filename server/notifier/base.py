"""Abstract Base Class for Notifier implementations."""

from abc import ABC, abstractmethod

from server.schemas import PushPayload


class BaseNotifier(ABC):
    """Abstract interface for dispatching download notifications."""

    @abstractmethod
    async def notify(self, payload: PushPayload) -> None:
        """Dispatches an evaluated PushPayload to the target device or channel."""
        pass
