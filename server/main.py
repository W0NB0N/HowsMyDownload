"""FastAPI application entry point for Download Notifs Backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.health import router as health_router
from server.api.samples import router as samples_router
from server.config import settings
from server.notifier.console import ConsoleNotifier
from server.tracker.manager import TrackerManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes runtime singletons (notifier, tracker) on startup."""
    # Phase 2: ConsoleNotifier is the active backend
    notifier = ConsoleNotifier()
    tracker_manager = TrackerManager(notifier=notifier)

    app.state.notifier = notifier
    app.state.tracker_manager = tracker_manager

    yield

    # Cleanup on shutdown if needed


def create_app() -> FastAPI:
    """Creates and configures the FastAPI instance."""
    app = FastAPI(
        title="Download Notifs Backend",
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
