"""Abstract Base Class for Notifier implementations."""

from abc import ABC, abstractmethod

from server.schemas import PushPayload


class BaseNotifier(ABC):
    """Abstract interface for dispatching download notifications."""

    @abstractmethod
    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        """Dispatches an evaluated PushPayload to the target device or channel."""
        pass

    async def send_unpair_event(self, token: str, pairing_id: str) -> None:
        """Sends an unpair notification signal to the device if supported."""
        return None
