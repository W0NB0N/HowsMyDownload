"""Abstract Base Class for Notifier implementations."""

from abc import ABC, abstractmethod

from server.schemas import CommandResultEvent, PushPayload


class BaseNotifier(ABC):
    """Abstract interface for dispatching download notifications."""

    @abstractmethod
    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        """Dispatches an evaluated PushPayload to the target device or channel."""
        pass

    async def send_unpair_event(self, token: str, pairing_id: str) -> None:
        """Sends an unpair notification signal to the device if supported."""
        return None

    async def send_command_result(self, token: str | None, event: CommandResultEvent) -> None:
        """Tells the device how a pause/resume/restart command ended, if supported."""
        return None
