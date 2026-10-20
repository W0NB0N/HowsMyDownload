"""A server restart with a persistent store (Firestore in production) must not break pairings.

Everything except the store is in-process memory, so a restart is simulated by building a
second app around the same store with a fresh tracker, throttler and notifier.
"""

from fastapi.testclient import TestClient

from server.main import create_app
from server.store.memory import InMemoryPairingStore
from server.tests.conftest import MockNotifier, create_claimed_pairing
from server.throttler.push_throttler import PushThrottler
from server.tracker.manager import TrackerManager


def _boot(
    store: InMemoryPairingStore, epoch: int
) -> tuple[TestClient, MockNotifier, PushThrottler]:
    notifier = MockNotifier()
    throttler = PushThrottler(notifier=notifier, epoch=epoch)
    app = create_app()
    app.state.pairing_store = store
    app.state.notifier = notifier
    app.state.tracker_manager = TrackerManager(notifier=notifier, throttler=throttler)
    return TestClient(app), notifier, throttler


def _sample(pairing_id: str, bytes_dl: int, ts: str) -> dict:
    return {
        "pairing_id": pairing_id,
        "timestamp": ts,
        "downloads": [{
            "id": "d1", "filename": "enc:v1:a:b", "bytes_downloaded": bytes_dl,
            "total_bytes": 10_000, "state": "downloading",
        }],
    }


def test_mid_download_continues_after_restart():
    store = InMemoryPairingStore()
    client, _, before = _boot(store, epoch=1)
    pairing = create_claimed_pairing(client)
    auth = {"Authorization": f"Bearer {pairing['secret']}"}
    pid = pairing["pairing_id"]
    assert client.post(
        "/v1/samples", json=_sample(pid, 1_000, "2026-10-20T12:00:00Z"), headers=auth
    ).status_code == 200

    # Restart: new process state, same store
    client, notifier, after = _boot(store, epoch=2)
    sample = _sample(pid, 5_000, "2026-10-20T12:00:02Z")
    resp = client.post("/v1/samples", json=sample, headers=auth)

    assert resp.status_code == 200, resp.text
    assert after.epoch != before.epoch
    pushed = notifier.dispatched[-1]
    assert pushed.downloads[0].id == "d1"
    assert pushed.downloads[0].bytes_downloaded == 5_000
