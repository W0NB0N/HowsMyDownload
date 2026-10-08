"""Firebase Cloud Messaging (FCM) Notifier backend."""

import asyncio
import json
import logging
import os
from datetime import timedelta

import firebase_admin
from firebase_admin import credentials, exceptions, messaging
from server.notifier.base import BaseNotifier
from server.schemas import PushPayload

logger = logging.getLogger("notifs.notifier.fcm")


class FCMNotifier(BaseNotifier):
    """Dispatches high-priority data messages to Android devices via Firebase Cloud Messaging."""

    def __init__(
        self,
        cred_path: str | None = None,
        default_token: str | None = None,
    ) -> None:
        self.default_token = default_token
        self.cred_path = cred_path

        self._init_firebase(cred_path)

    def _init_firebase(self, cred_path: str | None) -> None:
        """Initializes the Firebase Admin SDK if not already initialized."""
        if firebase_admin._apps:
            return

        env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        resolved_path = cred_path or env_path or "server/service-account.json"
        if os.path.exists(resolved_path):
            try:
                cred = credentials.Certificate(resolved_path)
                firebase_admin.initialize_app(cred)
                logger.info(
                    "Firebase Admin SDK initialized with credentials from: %s",
                    resolved_path,
                )
            except Exception as e:
                logger.error(
                    "Failed to initialize Firebase Admin SDK with %s: %s",
                    resolved_path,
                    e,
                )
        else:
            logger.warning(
                "Firebase credentials not found at '%s'. FCM notifications will be skipped.",
                resolved_path,
            )

    async def notify(self, payload: PushPayload, target_token: str | None = None) -> None:
        """Sends a high-priority FCM data message for the given PushPayload."""
        token = target_token or self.default_token

        if not token:
            logger.debug("No FCM target token configured or provided. Skipping FCM push.")
            return

        if not firebase_admin._apps:
            logger.warning("Firebase Admin SDK not initialized. Cannot dispatch FCM push.")
            return

        # Prepare JSON payload conforming to Protocol Schema v1
        downloads_data = [item.model_dump(mode="json") for item in payload.downloads]
        data_payload = {
            "seq": str(payload.seq),
            "sent_at": payload.sent_at.isoformat(),
            "source": payload.source,
            "pc_name": payload.pc_name,
            "pairing_id": payload.pairing_id,
            "downloads": json.dumps(downloads_data),
        }

        # Build high-priority data-only message (TTL 30s)
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
        except messaging.UnregisteredError:
            logger.warning(
                "[FCM] Device token is no longer registered or has been uninstalled: %s...",
                token[:12],
            )
        except exceptions.FirebaseError as fe:
            logger.error("[FCM] Firebase delivery error: %s", fe)
        except Exception as e:
            logger.error("[FCM] Unexpected error sending FCM message: %s", e)

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
