"""FastAPI application entry point for Download Notifs Backend."""

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from server.api.commands import router as commands_router
from server.api.commands import run_expiry_sweeper
from server.api.health import router as health_router
from server.api.pairings import router as pairings_router
from server.api.samples import router as samples_router
from server.commands.queue import CommandQueue
from server.config import settings
from server.firebase_app import init_firebase
from server.notifier.composite import CompositeNotifier
from server.notifier.console import ConsoleNotifier
from server.notifier.fcm import FCMNotifier
from server.store.base import BasePairingStore
from server.store.cached import CachedPairingStore
from server.store.firestore import FirestorePairingStore
from server.store.memory import InMemoryPairingStore
from server.throttler.push_throttler import PushThrottler
from server.tracker.manager import TrackerManager

logger = logging.getLogger("notifs.main")

MAX_BODY_BYTES = 50 * 1024


def build_pairing_store() -> BasePairingStore:
    """Creates the configured store. Fails fast rather than silently losing pairings."""
    store_type = settings.STORE_TYPE.lower()
    if store_type == "firestore":
        if not init_firebase(settings.GOOGLE_APPLICATION_CREDENTIALS):
            raise RuntimeError(
                "STORE_TYPE=firestore but Firebase could not be initialized. Check "
                "GOOGLE_APPLICATION_CREDENTIALS, or set STORE_TYPE=memory for local dev."
            )
        # Cache auth lookups: otherwise every sample costs a Firestore query
        return CachedPairingStore(FirestorePairingStore())
    if store_type == "memory":
        return InMemoryPairingStore()
    raise RuntimeError(f"Unsupported STORE_TYPE={settings.STORE_TYPE!r} (use memory|firestore)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes runtime singletons (store, notifier, tracker) on startup."""
    pairing_store = build_pairing_store()

    notifier_type = settings.NOTIFIER_TYPE.lower()
    if notifier_type in ("fcm", "both", "multi"):
        # Dual output: Console logs + FCM push notifications
        fcm_notifier = FCMNotifier(
            cred_path=settings.GOOGLE_APPLICATION_CREDENTIALS,
            default_token=settings.target_fcm_token,
            store=pairing_store,
        )
        notifier = CompositeNotifier([ConsoleNotifier(), fcm_notifier])
    else:
        notifier = ConsoleNotifier()

    # The throttler owns seq numbers and the boot epoch; all of this state is in-process,
    # which is why the server must run as a single worker.
    throttler = PushThrottler(notifier=notifier, min_interval_sec=2.0)
    tracker_manager = TrackerManager(
        notifier=notifier,
        cleanup_ttl_sec=30.0,
        throttler=throttler,
    )

    app.state.pairing_store = pairing_store
    app.state.notifier = notifier
    app.state.throttler = throttler
    app.state.tracker_manager = tracker_manager
    # Phone -> PC commands; in-process like the tracker (single worker)
    app.state.command_queue = CommandQueue()
    expiry_sweeper = asyncio.create_task(run_expiry_sweeper(app))
    logger.info("Server started: store=%s notifier=%s epoch=%d",
                type(pairing_store).__name__, notifier_type, throttler.epoch)

    yield

    expiry_sweeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await expiry_sweeper
    await tracker_manager.close()


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Rejects request bodies over `max_bytes` with 413, including chunked uploads.

    Content-Length is checked up front. Bodies without one are buffered up to the limit and
    replayed to the app, so an oversized chunked stream is cut off before it is parsed.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = dict(scope["headers"]).get(b"content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self.max_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._reject(send)
                return
            await self.app(scope, receive, send)
            return

        try:
            body = await self._read_body(receive)
        except _BodyTooLarge:
            await self._reject(send)
            return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)

    async def _read_body(self, receive: Receive) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                raise _BodyTooLarge
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        return b"".join(chunks)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            {"detail": f"Payload too large. Maximum allowed size is {self.max_bytes // 1024}KB."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def create_app() -> FastAPI:
    """Creates and configures the FastAPI instance."""
    app = FastAPI(
        title="How's My Download Backend",
        version="0.1.0",
        description="FastAPI service mirroring PC download progress to mobile notifications.",
        lifespan=lifespan,
    )

    # Auth is a bearer header, never a cookie, so credentialed CORS is unnecessary. The
    # extension itself bypasses CORS via host_permissions.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    # Added last so it runs first: oversized bodies are rejected before anything else.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)

    app.include_router(health_router)
    app.include_router(samples_router)
    app.include_router(pairings_router)
    app.include_router(commands_router)

    @app.get("/")
    async def root():
        return {"service": "How's My Download Backend", "status": "online"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
