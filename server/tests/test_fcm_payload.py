"""Tests for the FCM 4KB data payload budget (bug: oversized pushes used to unpair users)."""

import json
from unittest.mock import patch

import pytest

from server.notifier.fcm import (
    FCM_DATA_BUDGET_BYTES,
    FCM_DATA_LIMIT_BYTES,
    FCMNotifier,
    _data_size,
    build_data_payload,
)
from server.schemas import DownloadState, EvaluatedDownloadItem, PushPayload


def _encrypted_name(length: int) -> str:
    # Shape of a real enc:v1 ciphertext; content is irrelevant to sizing
    return "enc:v1:AAAAAAAAAAAAAAAA:" + "B" * length


def _item(dl_id: str, state=DownloadState.DOWNLOADING, name_len: int = 40) -> EvaluatedDownloadItem:
    return EvaluatedDownloadItem(
        id=dl_id,
        filename=_encrypted_name(name_len),
        percentage=12.5,
        speed=1_000_000,
        eta_seconds=60,
        state=state,
        bytes_downloaded=125,
        total_bytes=1000,
        mime_type="enc:v1:AAAAAAAAAAAAAAAA:" + "C" * 60,
    )


def _payload(items: list[EvaluatedDownloadItem]) -> PushPayload:
    return PushPayload(seq=7, epoch=1234, pairing_id="p-1", downloads=items)


def test_small_payload_is_complete_and_compact():
    unknown_total = EvaluatedDownloadItem(
        id="u", filename="enc:v1:x:y", state=DownloadState.STARTING, bytes_downloaded=0
    )
    data = build_data_payload(_payload([_item("a"), unknown_total]))

    assert data["seq"] == "7"
    assert data["epoch"] == "1234"
    assert "omitted" not in data
    downloads = json.loads(data["downloads"])
    assert [d["id"] for d in downloads] == ["a", "u"]
    # mime_type is never needed by the phone; nulls are optional and dropped
    assert all("mime_type" not in d for d in downloads)
    assert "total_bytes" not in downloads[1] and "percentage" not in downloads[1]
    assert all(isinstance(v, str) for v in data.values())


def test_many_long_downloads_are_trimmed_under_fcm_limit():
    items = [_item(f"dl-{i:02d}", name_len=1000) for i in range(40)]
    data = build_data_payload(_payload(items))

    assert _data_size(data) <= FCM_DATA_BUDGET_BYTES < FCM_DATA_LIMIT_BYTES
    downloads = json.loads(data["downloads"])
    assert 0 < len(downloads) < 40
    assert int(data["omitted"]) == 40 - len(downloads)


def test_terminal_transitions_are_kept_when_trimming():
    active = [_item(f"a-{i:02d}", name_len=800) for i in range(10)]
    done = _item("z-done", state=DownloadState.COMPLETED, name_len=800)
    failed = _item("z-failed", state=DownloadState.FAILED, name_len=800)
    data = build_data_payload(_payload([*active, done, failed]))

    ids = [d["id"] for d in json.loads(data["downloads"])]
    assert ids[:2] == ["z-done", "z-failed"]
    assert "omitted" in data


def test_single_item_larger_than_budget_is_dropped_not_sent():
    data = build_data_payload(_payload([_item("huge", name_len=5000), _item("ok")]))
    assert [d["id"] for d in json.loads(data["downloads"])] == ["ok"]
    assert data["omitted"] == "1"
    assert _data_size(data) <= FCM_DATA_BUDGET_BYTES


@pytest.mark.asyncio
async def test_notify_sends_budgeted_payload():
    items = [_item(f"dl-{i:02d}", name_len=1000) for i in range(25)]
    with (
        patch("server.notifier.fcm.firebase_admin._apps", {"default": object()}),
        patch("server.notifier.fcm.messaging.send", return_value="msg-1") as send,
    ):
        await FCMNotifier(default_token="tok").notify(_payload(items))

    message = send.call_args[0][0]
    assert _data_size(message.data) <= FCM_DATA_BUDGET_BYTES
    assert message.data["epoch"] == "1234"
    assert "omitted" in message.data
