"""Pytest fixtures and configuration."""

import pytest
from fastapi.testclient import TestClient
from server.main import create_app
from server.notifier.base import BaseNotifier
from server.schemas import PushPayload
from server.tracker.manager import TrackerManager


class MockNotifier(BaseNotifier):
    """Test notifier collecting all dispatched push payloads in memory."""

    def __init__(self) -> None:
        self.dispatched: list[PushPayload] = []

    async def notify(self, payload: PushPayload) -> None:
        self.dispatched.append(payload)


@pytest.fixture
def mock_notifier() -> MockNotifier:
    return MockNotifier()


@pytest.fixture
def tracker_manager(mock_notifier: MockNotifier) -> TrackerManager:
    return TrackerManager(notifier=mock_notifier)


@pytest.fixture
def app(mock_notifier: MockNotifier, tracker_manager: TrackerManager):
    app = create_app()
    app.state.notifier = mock_notifier
    app.state.tracker_manager = tracker_manager
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
