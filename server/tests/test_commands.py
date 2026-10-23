"""Phone -> PC download commands: queueing, delivery, expiry and result forwarding."""

import json

import pytest
from fastapi.testclient import TestClient

from server.api.commands import notify_expired_commands
from server.commands.queue import CommandQueue
from server.notifier.fcm import build_command_result_data, build_data_payload
from server.schemas import (
    CommandAction,
    CommandErrorCode,
    CommandResultEvent,
    DownloadState,
    EvaluatedDownloadItem,
    PushPayload,
)
from server.tests.conftest import MockNotifier, create_claimed_pairing


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def _send(client: TestClient, pairing: dict, download_id="42", action="pause"):
    return client.post(
        f"/v1/pairings/{pairing['pairing_id']}/commands",
        json={"download_id": download_id, "action": action},
        headers=_bearer(pairing["device_secret"]),
    )


def _collect(client: TestClient, pairing: dict):
    return client.get(
        f"/v1/pairings/{pairing['pairing_id']}/commands",
        headers=_bearer(pairing["secret"]),
    )


def _sample(client: TestClient, pairing: dict, state="downloading", **extra):
    item = {
        "id": "42",
        "filename": "enc:v1:aaaa:bbbb",
        "bytes_downloaded": 10,
        "total_bytes": 100,
        "state": state,
        **extra,
    }
    return client.post(
        "/v1/samples",
        json={"pairing_id": pairing["pairing_id"], "downloads": [item]},
        headers=_bearer(pairing["secret"]),
    )


@pytest.fixture
def pairing(client: TestClient) -> dict:
    return create_claimed_pairing(client)


# --- queueing ---------------------------------------------------------------------------


def test_device_queues_command(client: TestClient, pairing: dict):
    resp = _send(client, pairing)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["command"]["download_id"] == "42"
    assert body["command"]["action"] == "pause"
    assert len(body["command"]["command_id"]) == 32
    assert body["expires_in_sec"] > 0
    assert body["pc_last_seen_sec"] is None  # extension not seen since boot


def test_extension_cannot_issue_commands(client: TestClient, pairing: dict):
    resp = client.post(
        f"/v1/pairings/{pairing['pairing_id']}/commands",
        json={"download_id": "42", "action": "pause"},
        headers=_bearer(pairing["secret"]),
    )
    assert resp.status_code == 403


def test_wrong_secret_is_401(client: TestClient, pairing: dict):
    resp = client.post(
        f"/v1/pairings/{pairing['pairing_id']}/commands",
        json={"download_id": "42", "action": "pause"},
        headers=_bearer("nope"),
    )
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"download_id": "42", "action": "delete"},
        {"download_id": "../42", "action": "pause"},
        {"download_id": "", "action": "pause"},
        {"download_id": "x" * 129, "action": "pause"},
        {"action": "pause"},
    ],
)
def test_invalid_command_is_422(client: TestClient, pairing: dict, body: dict):
    resp = client.post(
        f"/v1/pairings/{pairing['pairing_id']}/commands",
        json=body,
        headers=_bearer(pairing["device_secret"]),
    )
    assert resp.status_code == 422


def test_command_send_is_rate_limited(client: TestClient, pairing: dict):
    codes = [_send(client, pairing, download_id=str(i)).status_code for i in range(21)]
    assert codes[:20] == [202] * 20
    assert codes[20] == 429


# --- delivery -----------------------------------------------------------------------------


def test_extension_collects_commands_once(client: TestClient, pairing: dict):
    sent = _send(client, pairing).json()["command"]

    first = _collect(client, pairing)
    assert first.status_code == 200
    assert [c["command_id"] for c in first.json()["commands"]] == [sent["command_id"]]
    assert _collect(client, pairing).json()["commands"] == []


def test_device_cannot_collect_commands(client: TestClient, pairing: dict):
    resp = client.get(
        f"/v1/pairings/{pairing['pairing_id']}/commands",
        headers=_bearer(pairing["device_secret"]),
    )
    assert resp.status_code == 403


def test_commands_ride_back_on_sample_response(client: TestClient, pairing: dict):
    sent = _send(client, pairing, action="restart").json()["command"]

    resp = _sample(client, pairing)
    assert resp.status_code == 200
    commands = resp.json()["commands"]
    assert [(c["command_id"], c["action"]) for c in commands] == [(sent["command_id"], "restart")]

    # Handed over exactly once
    assert _sample(client, pairing).json()["commands"] == []
    assert _collect(client, pairing).json()["commands"] == []


def test_sample_response_has_empty_command_list_by_default(client: TestClient, pairing: dict):
    assert _sample(client, pairing).json()["commands"] == []


def test_pc_last_seen_reported_after_extension_contact(client: TestClient, pairing: dict):
    _sample(client, pairing)
    assert _send(client, pairing).json()["pc_last_seen_sec"] == 0


def test_newer_tap_supersedes_pending_command_for_same_download(
    client: TestClient, pairing: dict
):
    _send(client, pairing, action="pause")
    resumed = _send(client, pairing, action="resume").json()["command"]
    _send(client, pairing, download_id="7", action="pause")

    commands = _collect(client, pairing).json()["commands"]
    by_download = {c["download_id"]: c for c in commands}
    assert set(by_download) == {"42", "7"}
    assert by_download["42"]["action"] == "resume"
    assert by_download["42"]["command_id"] == resumed["command_id"]


def test_double_tap_returns_the_same_command(client: TestClient, pairing: dict):
    first = _send(client, pairing).json()["command"]["command_id"]
    second = _send(client, pairing).json()["command"]["command_id"]
    assert first == second
    assert len(_collect(client, pairing).json()["commands"]) == 1


def test_unpair_drops_pending_commands(
    client: TestClient, pairing: dict, command_queue: CommandQueue
):
    _send(client, pairing)
    assert command_queue.pending_count(pairing["pairing_id"]) == 1
    resp = client.delete(
        f"/v1/pairings/{pairing['pairing_id']}", headers=_bearer(pairing["secret"])
    )
    assert resp.status_code == 200
    assert command_queue.pending_count(pairing["pairing_id"]) == 0
    assert command_queue.seconds_since_seen(pairing["pairing_id"]) is None


# --- results ------------------------------------------------------------------------------


def _report(client: TestClient, pairing: dict, command_id: str, secret_key="secret", **body):
    return client.post(
        f"/v1/pairings/{pairing['pairing_id']}/commands/{command_id}/result",
        json={"download_id": "42", "action": "resume", **body},
        headers=_bearer(pairing[secret_key]),
    )


def test_failed_result_is_pushed_to_phone(
    client: TestClient, pairing: dict, mock_notifier: MockNotifier
):
    resp = _report(client, pairing, "a" * 32, ok=False, error="not_resumable")
    assert resp.status_code == 200

    [(token, event)] = mock_notifier.command_results
    assert token == "fcm_token_123"
    assert event.pairing_id == pairing["pairing_id"]
    assert event.command_id == "a" * 32
    assert event.action == CommandAction.RESUME
    assert event.ok is False
    assert event.error == CommandErrorCode.NOT_RESUMABLE


def test_successful_result_is_not_pushed(
    client: TestClient, pairing: dict, mock_notifier: MockNotifier
):
    assert _report(client, pairing, "b" * 32, ok=True).status_code == 200
    assert mock_notifier.command_results == []


def test_failure_without_code_defaults_to_browser_error(
    client: TestClient, pairing: dict, mock_notifier: MockNotifier
):
    _report(client, pairing, "c" * 32, ok=False)
    assert mock_notifier.command_results[0][1].error == CommandErrorCode.BROWSER_ERROR


def test_result_rejects_free_text_errors_and_bad_ids(client: TestClient, pairing: dict):
    assert _report(client, pairing, "d" * 32, ok=False, error="disk on fire").status_code == 422
    assert _report(client, pairing, "not-a-command-id", ok=False).status_code == 422


def test_device_cannot_report_results(client: TestClient, pairing: dict):
    resp = _report(client, pairing, "e" * 32, secret_key="device_secret", ok=False)
    assert resp.status_code == 403


# --- expiry -------------------------------------------------------------------------------


async def test_expired_commands_notify_the_phone(client: TestClient, app, pairing: dict):
    app.state.command_queue = CommandQueue(ttl_sec=0.0)
    sent = _send(client, pairing, action="resume").json()["command"]

    # Expired commands are never handed to the extension...
    assert _collect(client, pairing).json()["commands"] == []

    # ...the sweeper tells the phone instead
    notifier: MockNotifier = app.state.notifier
    count = await notify_expired_commands(
        app.state.command_queue, app.state.pairing_store, notifier
    )
    assert count == 1
    [(token, event)] = notifier.command_results
    assert token == "fcm_token_123"
    assert event.command_id == sent["command_id"]
    assert event.ok is False
    assert event.error == CommandErrorCode.EXPIRED

    # Each expiry is reported once
    assert await notify_expired_commands(
        app.state.command_queue, app.state.pairing_store, notifier
    ) == 0


async def test_expired_commands_for_deleted_pairing_are_dropped_silently(
    pairing_store, mock_notifier: MockNotifier
):
    queue = CommandQueue(ttl_sec=0.0)
    queue.enqueue("gone", "1", CommandAction.PAUSE)
    assert await notify_expired_commands(queue, pairing_store, mock_notifier) == 1
    assert mock_notifier.command_results == []


def test_queue_bounds_pending_commands_per_pairing():
    queue = CommandQueue(max_per_pairing=3)
    for i in range(5):
        queue.enqueue("p", str(i), CommandAction.PAUSE)
    assert [c.download_id for c in queue.drain("p")] == ["2", "3", "4"]


def test_lifespan_creates_command_queue(monkeypatch):
    from server import main

    monkeypatch.setattr(main.settings, "STORE_TYPE", "memory")
    monkeypatch.setattr(main.settings, "NOTIFIER_TYPE", "console")
    with TestClient(main.create_app()) as client:
        assert isinstance(client.app.state.command_queue, CommandQueue)


# --- can_resume ---------------------------------------------------------------------------


def test_can_resume_is_forwarded_only_for_failed_downloads(
    client: TestClient, pairing: dict, mock_notifier: MockNotifier
):
    _sample(client, pairing, state="downloading", can_resume=True)
    assert mock_notifier.dispatched[-1].downloads[0].can_resume is None

    _sample(client, pairing, state="failed", can_resume=True)
    assert mock_notifier.dispatched[-1].downloads[0].can_resume is True

    _sample(client, pairing, state="failed")
    assert mock_notifier.dispatched[-1].downloads[0].can_resume is None


def test_fcm_payload_carries_can_resume_without_nulls():
    def item(state, can_resume):
        return EvaluatedDownloadItem(
            id="1", filename="f", state=state, bytes_downloaded=1, can_resume=can_resume
        )

    data = build_data_payload(
        PushPayload(
            seq=1,
            pairing_id="p",
            downloads=[item(DownloadState.FAILED, True), item(DownloadState.PAUSED, None)],
        )
    )
    failed, paused = json.loads(data["downloads"])
    assert failed["can_resume"] is True
    assert "can_resume" not in paused


def test_command_result_fcm_data_is_a_flat_string_map():
    data = build_command_result_data(
        CommandResultEvent(
            pairing_id="p",
            command_id="f" * 32,
            download_id="42",
            action=CommandAction.RESTART,
            ok=False,
            error=CommandErrorCode.UNSUPPORTED_URL,
        )
    )
    assert data == {
        "event": "command_result",
        "pairing_id": "p",
        "command_id": "f" * 32,
        "download_id": "42",
        "action": "restart",
        "ok": "false",
        "error": "unsupported_url",
    }
    assert all(isinstance(v, str) for v in data.values())
