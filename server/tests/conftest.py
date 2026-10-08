"""Pytest fixtures and configuration."""


import pytest
from fastapi.testclient import TestClient
from server.main import create_app
from server.notifier.base import BaseNotifier
from server.schemas import PushPayload
from server.store.memory import InMemoryPairingStore
from server.tracker.manager import TrackerManager


class MockNotifier(BaseNotifier):
    """Test notifier collecting all dispatched push payloads in memory."""

    def __init__(self) -> None:
        self.dispatched: list[PushPayload] = []
        self.target_tokens: list[str | None] = []

    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        self.dispatched.append(payload)
        self.target_tokens.append(target_token)


@pytest.fixture
def mock_notifier() -> MockNotifier:
    return MockNotifier()


@pytest.fixture
def pairing_store() -> InMemoryPairingStore:
    return InMemoryPairingStore()


@pytest.fixture
def tracker_manager(mock_notifier: MockNotifier) -> TrackerManager:
    return TrackerManager(notifier=mock_notifier)


@pytest.fixture
def app(
    mock_notifier: MockNotifier,
    tracker_manager: TrackerManager,
    pairing_store: InMemoryPairingStore,
):
    app = create_app()
    app.state.pairing_store = pairing_store
    app.state.notifier = mock_notifier
    app.state.tracker_manager = tracker_manager
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
