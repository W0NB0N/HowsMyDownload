"""Robustness: slow sends, ordering, clock skew, odd source transitions, idle eviction."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from server.notifier.base import BaseNotifier
from server.schemas import (
    DownloadState,
    EvaluatedDownloadItem,
    PushPayload,
    SamplePayload,
    SourceDownloadItem,
)
from server.tests.conftest import MockNotifier, create_claimed_pairing
from server.throttler.push_throttler import PushThrottler
from server.tracker.manager import TrackerManager


class SlowNotifier(BaseNotifier):
    """Blocks sends for one pairing until released; records completion order."""

    def __init__(self, slow_pairing: str) -> None:
        self.slow_pairing = slow_pairing
        self.release = asyncio.Event()
        self.sent: list[tuple[str, int]] = []

    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        if payload.pairing_id == self.slow_pairing:
            await self.release.wait()
        self.sent.append((payload.pairing_id, payload.seq))


def _sample(pairing: str, state=DownloadState.STARTING, bytes_dl=0, ts=None) -> SamplePayload:
    return SamplePayload(
        pairing_id=pairing,
        timestamp=ts or datetime.now(UTC),
        downloads=[
            SourceDownloadItem(
                id="d1", filename="enc:v1:a:b", bytes_downloaded=bytes_dl,
                total_bytes=1_000_000_000, state=state,
            )
        ],
    )


@pytest.mark.asyncio
async def test_slow_fcm_send_does_not_block_other_pairings():
    notifier = SlowNotifier(slow_pairing="slow")
    tracker = TrackerManager(notifier, throttler=PushThrottler(notifier))

    stuck = asyncio.create_task(tracker.process_sample(_sample("slow")))
    await asyncio.sleep(0)
    await asyncio.wait_for(tracker.process_sample(_sample("fast")), timeout=1)

    assert notifier.sent == [("fast", 1)]
    notifier.release.set()
    await stuck
    assert notifier.sent[-1] == ("slow", 1)


@pytest.mark.asyncio
async def test_same_pairing_sends_stay_in_seq_order():
    notifier = SlowNotifier(slow_pairing="p")
    throttler = PushThrottler(notifier, min_interval_sec=0)
    states = [DownloadState.STARTING, DownloadState.DOWNLOADING, DownloadState.PAUSED]
    tasks = []
    for state in states:
        item = EvaluatedDownloadItem(id="d1", filename="x", state=state, bytes_downloaded=0)
        payload = PushPayload(seq=1, pairing_id="p", downloads=[item])
        tasks.append(asyncio.create_task(throttler.submit(payload)))
        await asyncio.sleep(0)

    notifier.release.set()
    await asyncio.gather(*tasks)
    assert [seq for _, seq in notifier.sent] == [1, 2, 3]


@pytest.mark.asyncio
@pytest.mark.parametrize("skew", [timedelta(hours=-3), timedelta(hours=3)])
async def test_speed_is_correct_when_pc_clock_is_skewed(skew):
    """Speed used to mix server time (first point) with PC time (later points)."""
    notifier = MockNotifier()
    tracker = TrackerManager(notifier)
    t0 = datetime.now(UTC) + skew

    await tracker.process_sample(_sample("p", DownloadState.DOWNLOADING, 0, t0))
    for i in range(1, 6):
        await tracker.process_sample(
            _sample("p", DownloadState.DOWNLOADING, i * 20_000_000, t0 + timedelta(seconds=2 * i))
        )

    speed = notifier.dispatched[-1].downloads[0].speed
    assert 9_000_000 <= speed <= 11_000_000  # 20 MB per 2 s


@pytest.mark.asyncio
async def test_illegal_transition_resets_instead_of_failing(client):
    """Chrome restarting a download from 0 bytes (downloading -> starting) used to 500
    every retry, wedging the extension's backoff loop."""
    pairing = create_claimed_pairing(client)
    headers = {"Authorization": f"Bearer {pairing['secret']}"}

    def body(state, bytes_dl):
        return {
            "pairing_id": pairing["pairing_id"],
            "downloads": [{"id": "d1", "filename": "enc:v1:a:b",
                           "bytes_downloaded": bytes_dl, "state": state}],
        }

    first = client.post("/v1/samples", json=body("completed", 10), headers=headers)
    assert first.status_code == 200
    resp = client.post("/v1/samples", json=body("starting", 0), headers=headers)
    assert resp.status_code == 200
    assert resp.json()["processed"] == 1


@pytest.mark.asyncio
async def test_silent_downloads_are_evicted_after_idle_ttl(monkeypatch):
    tracker = TrackerManager(MockNotifier(), idle_ttl_sec=60)
    await tracker.process_sample(_sample("gone", DownloadState.DOWNLOADING, 5))
    assert tracker.get_active_count("gone") == 1

    real = time.monotonic
    monkeypatch.setattr("server.tracker.manager.time.monotonic", lambda: real() + 61)
    await tracker.process_sample(_sample("other"))
    assert tracker.get_active_count("gone") == 0
    assert tracker.get_active_count("other") == 1
