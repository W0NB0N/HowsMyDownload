"""Unit tests for TrackedDownload state transitions and TrackerManager."""

import pytest
from server.schemas import DownloadState, SamplePayload, SourceDownloadItem
from server.tests.conftest import MockNotifier
from server.tracker.download import InvalidStateTransitionError, TrackedDownload
from server.tracker.manager import TrackerManager


def test_tracked_download_valid_transitions():
    item = SourceDownloadItem(
        id="1",
        filename="test.iso",
        bytes_downloaded=0,
        total_bytes=100_000_000,
        state=DownloadState.STARTING,
    )
    tracked = TrackedDownload(item)
    assert tracked.state == DownloadState.STARTING

    # Transition to DOWNLOADING
    item.state = DownloadState.DOWNLOADING
    item.bytes_downloaded = 10_000_000
    eval_item = tracked.update(item, timestamp=2.0)
    assert eval_item.state == DownloadState.DOWNLOADING
    assert eval_item.percentage == 10.0

    # Transition to PAUSED
    item.state = DownloadState.PAUSED
    eval_item = tracked.update(item, timestamp=4.0)
    assert eval_item.state == DownloadState.PAUSED
    assert eval_item.speed == 0

    # Resume to DOWNLOADING
    item.state = DownloadState.DOWNLOADING
    item.bytes_downloaded = 20_000_000
    eval_item = tracked.update(item, timestamp=6.0)
    assert eval_item.state == DownloadState.DOWNLOADING

    # Complete
    item.state = DownloadState.COMPLETED
    item.bytes_downloaded = 100_000_000
    eval_item = tracked.update(item, timestamp=8.0)
    assert eval_item.state == DownloadState.COMPLETED
    assert eval_item.percentage == 100.0


def test_tracked_download_illegal_transition():
    item = SourceDownloadItem(
        id="2",
        filename="done.zip",
        bytes_downloaded=100,
        total_bytes=100,
        state=DownloadState.COMPLETED,
    )
    tracked = TrackedDownload(item)

    # Attempt to transition from COMPLETED back to DOWNLOADING -> must fail
    item.state = DownloadState.DOWNLOADING
    with pytest.raises(InvalidStateTransitionError):
        tracked.update(item)


@pytest.mark.asyncio
async def test_tracker_manager_multi_download_and_sequence(mock_notifier: MockNotifier):
    manager = TrackerManager(notifier=mock_notifier)

    sample1 = SamplePayload(
        pairing_id="pair-123",
        source="chrome",
        pc_name="Dev-PC",
        downloads=[
            SourceDownloadItem(
                id="d1",
                filename="ubuntu.iso",
                bytes_downloaded=50_000_000,
                total_bytes=100_000_000,
                state=DownloadState.DOWNLOADING,
            ),
            SourceDownloadItem(
                id="d2",
                filename="music.zip",
                bytes_downloaded=10_000,
                total_bytes=None,
                state=DownloadState.DOWNLOADING,
            ),
        ],
    )

    push1 = await manager.process_sample(sample1)
    assert push1.seq == 1
    assert len(push1.downloads) == 2
    assert len(mock_notifier.dispatched) == 1

    # Second sample should increment sequence number
    sample2 = SamplePayload(
        pairing_id="pair-123",
        downloads=[
            SourceDownloadItem(
                id="d1",
                filename="ubuntu.iso",
                bytes_downloaded=100_000_000,
                total_bytes=100_000_000,
                state=DownloadState.COMPLETED,
            )
        ],
    )
    push2 = await manager.process_sample(sample2)
    assert push2.seq == 2
    assert push2.downloads[0].state == DownloadState.COMPLETED
    assert len(mock_notifier.dispatched) == 2
