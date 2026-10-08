"""Unit tests for FCMNotifier and CompositeNotifier."""

from unittest.mock import MagicMock, patch

import pytest
from server.notifier.composite import CompositeNotifier
from server.notifier.fcm import FCMNotifier
from server.schemas import DownloadState, EvaluatedDownloadItem, PushPayload


@pytest.fixture
def sample_push_payload() -> PushPayload:
    return PushPayload(
        seq=42,
        source="chrome",
        pc_name="Test-Desktop",
        pairing_id="test-pair-1",
        downloads=[
            EvaluatedDownloadItem(
                id="dl-101",
                filename="archlinux.iso",
                percentage=64.2,
                speed=12_500_000,
                eta_seconds=45,
                state=DownloadState.DOWNLOADING,
                bytes_downloaded=642_000_000,
                total_bytes=1_000_000_000,
            )
        ],
    )


@pytest.mark.asyncio
async def test_fcm_notifier_dispatch(sample_push_payload: PushPayload):
    fake_msg_id = "projects/test/messages/msg-12345"
    with (
        patch("server.notifier.fcm.firebase_admin._apps", {"default": MagicMock()}),
        patch("server.notifier.fcm.messaging.send", return_value=fake_msg_id) as mock_send,
    ):
        notifier = FCMNotifier(default_token="mock-fcm-device-token-xyz")
        await notifier.notify(sample_push_payload)

        mock_send.assert_called_once()
        msg_arg = mock_send.call_args[0][0]

        assert msg_arg.token == "mock-fcm-device-token-xyz"
        assert msg_arg.data["seq"] == "42"
        assert msg_arg.data["source"] == "chrome"
        assert msg_arg.data["pc_name"] == "Test-Desktop"
        assert "archlinux.iso" in msg_arg.data["downloads"]
        assert msg_arg.android.priority == "high"


@pytest.mark.asyncio
async def test_fcm_notifier_no_token_skips(sample_push_payload: PushPayload):
    with patch("server.notifier.fcm.messaging.send") as mock_send:
        notifier = FCMNotifier(default_token=None)
        await notifier.notify(sample_push_payload)
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_composite_notifier_dispatches_all(sample_push_payload: PushPayload):
    mock1 = MagicMock()
    mock1.notify = MagicMock(return_value=None)

    # Async mock for notify
    async def async_notify1(p):
        mock1.notify(p)

    mock2 = MagicMock()

    async def async_notify2(p):
        mock2.notify(p)

    n1 = MagicMock()
    n1.notify = async_notify1
    n2 = MagicMock()
    n2.notify = async_notify2

    composite = CompositeNotifier([n1, n2])
    await composite.notify(sample_push_payload)

    mock1.notify.assert_called_once_with(sample_push_payload)
    mock2.notify.assert_called_once_with(sample_push_payload)
