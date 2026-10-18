"""Unit tests for PushThrottler.

Covers State-Change Bypass, Queue Coalescing, and Strict Sequence Numbering.
"""

import asyncio

import pytest
from server.schemas import DownloadState, EvaluatedDownloadItem, PushPayload
from server.tests.conftest import MockNotifier
from server.throttler.push_throttler import PushThrottler


def make_payload(pairing_id: str, dls: list[tuple[str, DownloadState, int]]) -> PushPayload:
    return PushPayload(
        seq=1,
        source="chrome",
        pc_name="Test-PC",
        pairing_id=pairing_id,
        downloads=[
            EvaluatedDownloadItem(
                id=dl_id,
                filename=f"{dl_id}.iso",
                state=state,
                bytes_downloaded=bytes_dl,
                total_bytes=1000,
                speed=100,
                percentage=float(bytes_dl) / 10.0,
            )
            for dl_id, state, bytes_dl in dls
        ],
    )


@pytest.mark.asyncio
async def test_throttler_state_change_bypass(mock_notifier: MockNotifier):
    throttler = PushThrottler(notifier=mock_notifier, min_interval_sec=1.0)

    # 1. First sample is starting/downloading -> immediate dispatch
    p1 = make_payload("pair-1", [("d1", DownloadState.STARTING, 0)])
    await throttler.submit(p1)
    assert len(mock_notifier.dispatched) == 1
    assert mock_notifier.dispatched[0].seq == 1
    assert mock_notifier.dispatched[0].downloads[0].state == DownloadState.STARTING

    # 2. State transition: STARTING -> DOWNLOADING -> immediate bypass
    p2 = make_payload("pair-1", [("d1", DownloadState.DOWNLOADING, 100)])
    await throttler.submit(p2)
    assert len(mock_notifier.dispatched) == 2
    assert mock_notifier.dispatched[1].seq == 2
    assert mock_notifier.dispatched[1].downloads[0].state == DownloadState.DOWNLOADING

    # 3. State transition: DOWNLOADING -> PAUSED -> immediate bypass
    p3 = make_payload("pair-1", [("d1", DownloadState.PAUSED, 100)])
    await throttler.submit(p3)
    assert len(mock_notifier.dispatched) == 3
    assert mock_notifier.dispatched[2].seq == 3
    assert mock_notifier.dispatched[2].downloads[0].state == DownloadState.PAUSED

    # 4. New download added -> immediate bypass
    p4 = make_payload(
        "pair-1",
        [("d1", DownloadState.PAUSED, 100), ("d2", DownloadState.STARTING, 0)],
    )
    await throttler.submit(p4)
    assert len(mock_notifier.dispatched) == 4
    assert mock_notifier.dispatched[3].seq == 4
    assert len(mock_notifier.dispatched[3].downloads) == 2

    # 5. Download d2 removed -> immediate bypass
    p5 = make_payload("pair-1", [("d1", DownloadState.PAUSED, 100)])
    await throttler.submit(p5)
    assert len(mock_notifier.dispatched) == 5
    assert mock_notifier.dispatched[4].seq == 5
    assert len(mock_notifier.dispatched[4].downloads) == 1

    # 6. Download d1 completed -> immediate bypass
    p6 = make_payload("pair-1", [("d1", DownloadState.COMPLETED, 1000)])
    await throttler.submit(p6)
    assert len(mock_notifier.dispatched) == 6
    assert mock_notifier.dispatched[5].seq == 6
    assert mock_notifier.dispatched[5].downloads[0].state == DownloadState.COMPLETED

    await throttler.close()


@pytest.mark.asyncio
async def test_throttler_flush(mock_notifier: MockNotifier):
    throttler = PushThrottler(notifier=mock_notifier, min_interval_sec=5.0)

    # First push -> immediate
    p1 = make_payload("pair-flush", [("d1", DownloadState.DOWNLOADING, 100)])
    await throttler.submit(p1)
    assert len(mock_notifier.dispatched) == 1

    # Buffered tick
    p2 = make_payload("pair-flush", [("d1", DownloadState.DOWNLOADING, 250)])
    await throttler.submit(p2)
    assert len(mock_notifier.dispatched) == 1

    # Explicit flush forces immediate dispatch
    await throttler.flush("pair-flush")
    assert len(mock_notifier.dispatched) == 2
    assert mock_notifier.dispatched[1].seq == 2
    assert mock_notifier.dispatched[1].downloads[0].bytes_downloaded == 250

    await throttler.close()


@pytest.mark.asyncio
async def test_throttler_queue_coalescing_and_sequence(mock_notifier: MockNotifier):
    throttler = PushThrottler(notifier=mock_notifier, min_interval_sec=0.2)

    # 1. Initial push (state change from None) -> immediate dispatch (seq 1)
    p1 = make_payload("pair-1", [("d1", DownloadState.DOWNLOADING, 100)])
    await throttler.submit(p1)
    assert len(mock_notifier.dispatched) == 1
    assert mock_notifier.dispatched[0].seq == 1

    # 2. Rapid progress ticks within throttle window (same state, just bytes increasing)
    p2 = make_payload("pair-1", [("d1", DownloadState.DOWNLOADING, 200)])
    p3 = make_payload("pair-1", [("d1", DownloadState.DOWNLOADING, 300)])
    p4 = make_payload("pair-1", [("d1", DownloadState.DOWNLOADING, 400)])

    await throttler.submit(p2)
    await throttler.submit(p3)
    await throttler.submit(p4)

    # Still only 1 dispatched over the wire
    assert len(mock_notifier.dispatched) == 1

    # Wait for the throttle window to expire and flush
    await asyncio.sleep(0.25)

    # Exactly 2 dispatched over the wire, and the second is the latest coalesced payload (p4)
    assert len(mock_notifier.dispatched) == 2
    assert mock_notifier.dispatched[1].seq == 2  # Strict sequence numbering, no gap!
    assert mock_notifier.dispatched[1].downloads[0].bytes_downloaded == 400

    await throttler.close()


@pytest.mark.asyncio
async def test_throttler_multi_pairing_isolation(mock_notifier: MockNotifier):
    throttler = PushThrottler(notifier=mock_notifier, min_interval_sec=1.0)

    pA = make_payload("pair-A", [("dA", DownloadState.DOWNLOADING, 100)])
    pB = make_payload("pair-B", [("dB", DownloadState.DOWNLOADING, 200)])

    await throttler.submit(pA)
    await throttler.submit(pB)

    # Both dispatch immediately because they are distinct pairings
    assert len(mock_notifier.dispatched) == 2
    assert mock_notifier.dispatched[0].pairing_id == "pair-A"
    assert mock_notifier.dispatched[0].seq == 1
    assert mock_notifier.dispatched[1].pairing_id == "pair-B"
    assert mock_notifier.dispatched[1].seq == 1

    await throttler.close()
