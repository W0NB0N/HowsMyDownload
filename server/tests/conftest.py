"""Pytest fixtures and configuration."""


import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.notifier.base import BaseNotifier
from server.rate_limiter import ALL_LIMITERS
from server.schemas import PushPayload
from server.store.memory import InMemoryPairingStore
from server.tracker.manager import TrackerManager


class MockNotifier(BaseNotifier):
    """Test notifier collecting all dispatched push payloads in memory."""

    def __init__(self) -> None:
        self.dispatched: list[PushPayload] = []
        self.target_tokens: list[str | None] = []
        self.unpair_events: list[tuple[str, str]] = []

    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        self.dispatched.append(payload)
        self.target_tokens.append(target_token)

    async def send_unpair_event(self, token: str, pairing_id: str) -> None:
        self.unpair_events.append((token, pairing_id))


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Rate limiters are module-level singletons; isolate them between tests."""
    for limiter in ALL_LIMITERS:
        limiter.reset()
    yield
    for limiter in ALL_LIMITERS:
        limiter.reset()


def create_claimed_pairing(client: TestClient, fcm_token: str = "fcm_token_123") -> dict:
    """Creates and claims a pairing; returns extension + device credentials."""
    created = client.post("/v1/pairings", json={"pc_name": "Test-PC"}).json()
    claim = client.post(f"/v1/pairings/{created['code']}/claim", json={"fcm_token": fcm_token})
    assert claim.status_code == 200, claim.text
    return {**created, "device_secret": claim.json()["device_secret"]}


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
