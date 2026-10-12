"""FastAPI application entry point for Download Notifs Backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.health import router as health_router
from server.api.pairings import router as pairings_router
from server.api.samples import router as samples_router
from server.config import settings
from server.notifier.composite import CompositeNotifier
from server.notifier.console import ConsoleNotifier
from server.notifier.fcm import FCMNotifier
from server.store.firestore import FirestorePairingStore
from server.store.memory import InMemoryPairingStore
from server.tracker.manager import TrackerManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes runtime singletons (store, notifier, tracker) on startup."""
    # 1. Initialize Pairing Store
    store_type = settings.STORE_TYPE.lower()
    if store_type == "firestore":
        try:
            pairing_store = FirestorePairingStore()
        except Exception:
            # Fallback to memory store if firestore unavailable
            pairing_store = InMemoryPairingStore()
    else:
        pairing_store = InMemoryPairingStore()

    # 2. Initialize Notifiers
    notifier_type = settings.NOTIFIER_TYPE.lower()
    if notifier_type in ("fcm", "both", "multi"):
        # Dual output: Console logs + FCM push notifications
        console_notifier = ConsoleNotifier()
        fcm_notifier = FCMNotifier(
            cred_path=settings.GOOGLE_APPLICATION_CREDENTIALS,
            default_token=settings.target_fcm_token,
            store=pairing_store,
        )
        notifier = CompositeNotifier([console_notifier, fcm_notifier])
    else:
        # Default: Console output only
        notifier = ConsoleNotifier()

    # 3. Rate limiting Throttler & Tracker Manager
    from server.throttler.push_throttler import PushThrottler

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

    yield

    # Cleanup on shutdown
    await tracker_manager.close()


def create_app() -> FastAPI:
    """Creates and configures the FastAPI instance."""
    app = FastAPI(
        title="How's My Download Backend",
        version="0.1.0",
        description="FastAPI service mirroring PC download progress to mobile notifications.",
        lifespan=lifespan,
    )

    # Enable CORS for Chrome Extension / local dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)
    app.include_router(samples_router)
    app.include_router(pairings_router)

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
