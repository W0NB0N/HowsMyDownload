"""Unit tests for FCMNotifier and CompositeNotifier."""

from unittest.mock import MagicMock, patch

import pytest
from firebase_admin import exceptions, messaging

from server.notifier.composite import CompositeNotifier
from server.notifier.fcm import FCMNotifier
from server.schemas import (
    CommandAction,
    CommandErrorCode,
    CommandResultEvent,
    DownloadState,
    EvaluatedDownloadItem,
    PushPayload,
)
from server.store.memory import InMemoryPairingStore


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


# --- Dead-token classification: which FCM errors may purge a pairing ------------------


async def _store_with_pairing(pairing_id: str) -> InMemoryPairingStore:
    store = InMemoryPairingStore()
    await store.create_pairing(pairing_id=pairing_id, code="CODE01", secret_hash="h", pc_name="PC")
    return store


async def _send_with_error(store: InMemoryPairingStore, pairing_id: str, error: Exception):
    payload = PushPayload(seq=1, pairing_id=pairing_id, downloads=[])
    with (
        patch("firebase_admin._apps", True),
        patch("firebase_admin.messaging.send", side_effect=error),
    ):
        await FCMNotifier(cred_path=None, store=store).notify(payload, target_token="tok")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        messaging.UnregisteredError("App uninstalled"),
        messaging.SenderIdMismatchError("Token belongs to another project"),
        exceptions.InvalidArgumentError(
            "The registration token is not a valid FCM registration token"
        ),
    ],
)
async def test_dead_token_errors_purge_pairing(error):
    store = await _store_with_pairing("pair-dead")
    await _send_with_error(store, "pair-dead", error)
    assert await store.get_pairing("pair-dead") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        # Rejected *message* (e.g. too big): says nothing about the token
        exceptions.InvalidArgumentError("Message is too big"),
        exceptions.UnavailableError("FCM temporarily unavailable"),
        messaging.QuotaExceededError("Quota exceeded"),
    ],
)
async def test_message_or_transient_errors_keep_pairing(error):
    store = await _store_with_pairing("pair-keep")
    await _send_with_error(store, "pair-keep", error)
    assert await store.get_pairing("pair-keep") is not None


# --- Command results ---------------------------------------------------------------------


def _command_failure(pairing_id: str = "pair-1") -> CommandResultEvent:
    return CommandResultEvent(
        pairing_id=pairing_id,
        command_id="0" * 32,
        download_id="42",
        action=CommandAction.RESUME,
        ok=False,
        error=CommandErrorCode.EXPIRED,
    )


@pytest.mark.asyncio
async def test_command_result_is_sent_as_high_priority_data_message():
    with (
        patch("server.notifier.fcm.firebase_admin._apps", {"default": MagicMock()}),
        patch("server.notifier.fcm.messaging.send", return_value="msg-1") as mock_send,
    ):
        await FCMNotifier().send_command_result("device-token", _command_failure())

    msg = mock_send.call_args[0][0]
    assert msg.token == "device-token"
    assert msg.data["event"] == "command_result"
    assert msg.data["ok"] == "false"
    assert msg.data["error"] == "expired"
    assert msg.android.priority == "high"


@pytest.mark.asyncio
async def test_command_result_dead_token_purges_pairing():
    store = await _store_with_pairing("pair-cmd")
    with (
        patch("firebase_admin._apps", True),
        patch("firebase_admin.messaging.send", side_effect=messaging.UnregisteredError("gone")),
    ):
        await FCMNotifier(store=store).send_command_result("tok", _command_failure("pair-cmd"))
    assert await store.get_pairing("pair-cmd") is None


@pytest.mark.asyncio
async def test_composite_fans_out_command_results():
    received = []

    class Recorder(FCMNotifier):
        def __init__(self):
            pass

        async def send_command_result(self, token, event):
            received.append((token, event.command_id))

    await CompositeNotifier([Recorder(), Recorder()]).send_command_result("t", _command_failure())
    assert received == [("t", "0" * 32), ("t", "0" * 32)]