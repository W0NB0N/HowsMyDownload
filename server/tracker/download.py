"""Per-download state machine and tracker."""

import time

from server.schemas import DownloadState, EvaluatedDownloadItem, SourceDownloadItem
from server.tracker.calculator import SpeedSmoother, calculate_eta, calculate_percentage


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal download state transition is attempted."""
    pass


class TrackedDownload:
    """Maintains the live tracking state, history, and computations for a single download item."""

    # Allowed state transitions
    VALID_TRANSITIONS: dict[DownloadState, set[DownloadState]] = {
        DownloadState.STARTING: {
            DownloadState.STARTING,
            DownloadState.DOWNLOADING,
            DownloadState.PAUSED,
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.ERASED,
        },
        DownloadState.DOWNLOADING: {
            DownloadState.DOWNLOADING,
            DownloadState.PAUSED,
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.ERASED,
            DownloadState.STALE,
        },
        DownloadState.PAUSED: {
            DownloadState.PAUSED,
            DownloadState.DOWNLOADING,
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.ERASED,
        },
        DownloadState.COMPLETED: {
            DownloadState.COMPLETED,
            DownloadState.ERASED,
        },
        DownloadState.FAILED: {
            DownloadState.FAILED,
            DownloadState.DOWNLOADING,  # Resumed/retried
            DownloadState.ERASED,
        },
        DownloadState.ERASED: {
            DownloadState.ERASED,
        },
        DownloadState.STALE: {
            DownloadState.STALE,
            DownloadState.DOWNLOADING,
            DownloadState.ERASED,
        },
    }

    def __init__(self, initial_item: SourceDownloadItem) -> None:
        self.id = initial_item.id
        self.filename = initial_item.filename
        self.bytes_downloaded = initial_item.bytes_downloaded
        self.total_bytes = initial_item.total_bytes
        self.state = initial_item.state
        self.mime_type = initial_item.mime_type

        self.created_at = time.time()
        self.last_updated_at = self.created_at
        self.smoother = SpeedSmoother()
        self.current_speed = 0

        # Initialize smoother with first point
        self.smoother.update(self.created_at, self.bytes_downloaded)

    def transition_to(self, new_state: DownloadState) -> None:
        """Validates and applies a state transition."""
        allowed = self.VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition download '{self.id}' ({self.filename}) "
                f"from {self.state.value} -> {new_state.value}"
            )
        self.state = new_state

    def update(
        self,
        item: SourceDownloadItem,
        timestamp: float | None = None,
    ) -> EvaluatedDownloadItem:
        """Applies an incoming sample tick to the tracked download."""
        now = timestamp if timestamp is not None else time.time()
        self.last_updated_at = now

        # Update metadata if refined
        if item.filename and item.filename != self.filename:
            self.filename = item.filename
        if item.total_bytes is not None:
            self.total_bytes = item.total_bytes
        if item.mime_type:
            self.mime_type = item.mime_type

        # Validate and apply state transition
        if item.state != self.state:
            self.transition_to(item.state)

        self.bytes_downloaded = item.bytes_downloaded

        # Compute speed
        terminal_or_paused = (
            DownloadState.PAUSED,
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.ERASED,
        )
        if self.state in terminal_or_paused:
            self.current_speed = 0
            self.smoother.reset()
        else:
            self.current_speed = self.smoother.update(now, self.bytes_downloaded)

        return self.to_evaluated()

    def to_evaluated(self) -> EvaluatedDownloadItem:
        """Produces the enriched EvaluatedDownloadItem."""
        pct = calculate_percentage(self.bytes_downloaded, self.total_bytes)
        eta = calculate_eta(self.bytes_downloaded, self.total_bytes, self.current_speed)

        return EvaluatedDownloadItem(
            id=self.id,
            filename=self.filename,
            percentage=pct,
            speed=self.current_speed,
            eta_seconds=eta,
            state=self.state,
            bytes_downloaded=self.bytes_downloaded,
            total_bytes=self.total_bytes,
            mime_type=self.mime_type,
        )
