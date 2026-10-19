"""Shared Firebase Admin SDK initialization used by the FCM notifier and Firestore store."""

import logging
import os

import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger("notifs.firebase")


def init_firebase(cred_path: str | None = None) -> bool:
    """Initializes the default Firebase app once. Returns True if an app is available."""
    if firebase_admin._apps:
        return True

    resolved_path = (
        cred_path
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or "server/service-account.json"
    )
    if not os.path.exists(resolved_path):
        logger.warning("Firebase credentials not found at '%s'.", resolved_path)
        return False

    try:
        firebase_admin.initialize_app(credentials.Certificate(resolved_path))
    except Exception as err:
        logger.error("Failed to initialize Firebase Admin SDK with %s: %s", resolved_path, err)
        return False

    logger.info("Firebase Admin SDK initialized with credentials from: %s", resolved_path)
    return True
