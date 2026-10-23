"""Firebase Cloud Messaging (FCM) Notifier backend."""

import asyncio
import json
import logging
from datetime import timedelta

import firebase_admin
from firebase_admin import exceptions, messaging

from server.firebase_app import init_firebase
from server.notifier.base import BaseNotifier
from server.schemas import CommandResultEvent, DownloadState, EvaluatedDownloadItem, PushPayload
from server.store.base import BasePairingStore

logger = logging.getLogger("notifs.notifier.fcm")

# FCM rejects data messages whose keys + values exceed 4096 bytes. Stay well under it so
# FCM-side overhead can never tip a message over and get it rejected with INVALID_ARGUMENT.
FCM_DATA_LIMIT_BYTES = 4096
FCM_DATA_BUDGET_BYTES = 3584

# Terminal transitions are one-shot events the phone must not miss, so they win over
# ongoing progress when the payload has to be trimmed.
_STATE_PRIORITY = {
    DownloadState.COMPLETED: 0,
    DownloadState.FAILED: 0,
    DownloadState.ERASED: 0,
    DownloadState.STARTING: 1,
    DownloadState.DOWNLOADING: 1,
    DownloadState.PAUSED: 2,
    DownloadState.STALE: 2,
}


def _data_size(data: dict[str, str]) -> int:
    return sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in data.items())


def _wire_item(item: EvaluatedDownloadItem) -> dict:
    # The phone never reads mime_type, and nulls are optional on the wire.
    return item.model_dump(mode="json", exclude={"mime_type"}, exclude_none=True)


def build_data_payload(
    payload: PushPayload,
    budget_bytes: int = FCM_DATA_BUDGET_BYTES,
) -> dict[str, str]:
    """Serializes a PushPayload into an FCM data map that always fits within `budget_bytes`.

    Downloads are added in priority order until the budget is reached. Encrypted filenames
    cannot be shortened without breaking authentication, so items that do not fit are dropped
    whole and counted in `omitted` (the phone then keeps their last-known notifications).
    """
    data = {
        "seq": str(payload.seq),
        "epoch": str(payload.epoch),
        "sent_at": payload.sent_at.isoformat(),
        "source": payload.source,
        "pc_name": payload.pc_name,
        "pairing_id": payload.pairing_id,
    }

    ordered = sorted(
        payload.downloads,
        key=lambda d: (_STATE_PRIORITY.get(d.state, 3), d.id),
    )
    # Reserve room for the "downloads" key, the JSON brackets, and an "omitted" entry.
    used = _data_size(data) + len("downloads") + 2 + len("omitted") + 4

    included: list[str] = []
    for item in ordered:
        encoded = json.dumps(_wire_item(item), separators=(",", ":"))
        cost = len(encoded.encode("utf-8")) + (1 if included else 0)
        if used + cost > budget_bytes:
            continue
        included.append(encoded)
        used += cost

    data["downloads"] = "[" + ",".join(included) + "]"
    omitted = len(payload.downloads) - len(included)
    if omitted:
        data["omitted"] = str(omitted)
        logger.warning(
            "[FCM] Payload for %s trimmed to fit 4KB: %d of %d downloads omitted",
            payload.pairing_id,
            omitted,
            len(payload.downloads),
        )
    return data


def build_command_result_data(event: CommandResultEvent) -> dict[str, str]:
    """FCM data map for a command outcome. Carries no `seq`: it is not part of the progress
    stream, and the phone handles it before the sequence gate."""
    data = {
        "event": "command_result",
        "pairing_id": event.pairing_id,
        "command_id": event.command_id,
        "download_id": event.download_id,
        "action": event.action.value,
        "ok": "true" if event.ok else "false",
    }
    if event.error is not None:
        data["error"] = event.error.value
    return data


def is_dead_token_error(err: Exception) -> bool:
    """True only for errors that mean the registration token can never work again.

    INVALID_ARGUMENT is also returned for malformed or oversized messages, so it only counts
    when FCM says the registration token itself is invalid.
    """
    if isinstance(err, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
        return True
    if isinstance(err, exceptions.InvalidArgumentError):
        return "registration token" in str(err).lower()
    return False


class FCMNotifier(BaseNotifier):
    """Dispatches high-priority data messages to Android devices via Firebase Cloud Messaging."""

    def __init__(
        self,
        cred_path: str | None = None,
        default_token: str | None = None,
        store: BasePairingStore | None = None,
    ) -> None:
        self.default_token = default_token
        self.cred_path = cred_path
        self.store = store

        if not init_firebase(cred_path):
            logger.warning("FCM notifications will be skipped until Firebase is configured.")

    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        """Sends a high-priority FCM data message for the given PushPayload."""
        token = target_token or self.default_token

        if not token:
            logger.debug("No FCM target token configured or provided. Skipping FCM push.")
            return

        if not firebase_admin._apps:
            logger.warning("Firebase Admin SDK not initialized. Cannot dispatch FCM push.")
            return

        data_payload = build_data_payload(payload)

        # High-priority data-only message (TTL 30s: stale progress is worthless)
        message = messaging.Message(
            data=data_payload,
            token=token,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=timedelta(seconds=30),
            ),
        )

        try:
            # Send asynchronously without blocking the event loop
            msg_id = await asyncio.to_thread(messaging.send, message)
            logger.info(
                "[FCM] Seq #%d dispatched to %s... -> MsgId: %s (%d downloads)",
                payload.seq,
                token[:12],
                msg_id,
                len(payload.downloads),
            )
        except exceptions.FirebaseError as err:
            if is_dead_token_error(err):
                await self._purge_pairing(payload.pairing_id, token, err)
            else:
                logger.error("[FCM] Delivery error for %s: %s", payload.pairing_id, err)
        except Exception as err:
            logger.error("[FCM] Unexpected error sending FCM message: %s", err)

    async def _purge_pairing(self, pairing_id: str, token: str, err: Exception) -> None:
        logger.warning("[FCM] Device token %s... is permanently invalid: %s", token[:12], err)
        if not (self.store and pairing_id):
            return
        try:
            logger.info("[FCM] Cleaning up revoked pairing: %s", pairing_id)
            await self.store.delete_pairing(pairing_id)
        except Exception as cleanup_err:
            logger.error(
                "[FCM] Failed to cleanup revoked pairing %s: %s",
                pairing_id,
                cleanup_err,
            )

    async def send_unpair_event(self, token: str, pairing_id: str) -> None:
        """Sends a high-priority unpair signal message to the paired Android device."""
        if not token or not firebase_admin._apps:
            return

        message = messaging.Message(
            data={
                "event": "unpaired",
                "pairing_id": pairing_id,
            },
            token=token,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=timedelta(seconds=10),
            ),
        )
        try:
            msg_id = await asyncio.to_thread(messaging.send, message)
            logger.info(
                "[FCM] Unpair signal dispatched to %s... -> MsgId: %s",
                token[:12],
                msg_id,
            )
        except Exception as e:
            logger.warning("[FCM] Could not send unpair signal to %s: %s", token[:12], e)

    async def send_command_result(self, token: str | None, event: CommandResultEvent) -> None:
        """Sends a high-priority command outcome (e.g. "PC didn't respond") to the phone."""
        token = token or self.default_token
        if not token or not firebase_admin._apps:
            return

        message = messaging.Message(
            data=build_command_result_data(event),
            token=token,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=timedelta(seconds=60),
            ),
        )
        try:
            msg_id = await asyncio.to_thread(messaging.send, message)
            logger.info(
                "[FCM] Command result (%s %s) dispatched to %s... -> MsgId: %s",
                event.action.value,
                "ok" if event.ok else event.error,
                token[:12],
                msg_id,
            )
        except exceptions.FirebaseError as err:
            if is_dead_token_error(err):
                await self._purge_pairing(event.pairing_id, token, err)
            else:
                logger.error("[FCM] Command result delivery error for %s: %s",
                             event.pairing_id, err)
        except Exception as err:
            logger.error("[FCM] Unexpected error sending command result: %s", err)
