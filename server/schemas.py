"""Pydantic schemas and data models conforming to Protocol Schema v1."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from server import __version__


def utc_now() -> datetime:
    return datetime.now(UTC)


# Server-issued identifiers: pairing IDs are UUID4 strings, claim codes are 6 chars drawn
# from an unambiguous uppercase alphabet (case-insensitive on input).
PAIRING_ID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
PAIRING_CODE_PATTERN = r"^[A-Za-z0-9]{6}$"


class DownloadState(StrEnum):
    STARTING = "starting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ERASED = "erased"
    STALE = "stale"


class SourceDownloadItem(BaseModel):
    """A single download item reported by a source (Extension/Client)."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique ID per download item in source",
    )
    filename: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="File name or encrypted string",
    )
    bytes_downloaded: int = Field(
        ...,
        ge=0,
        le=10_000_000_000_000_000,
        description="Current received bytes",
    )
    total_bytes: int | None = Field(
        default=None,
        ge=0,
        le=10_000_000_000_000_000,
        description="Total expected bytes, null if unknown",
    )
    state: DownloadState = Field(..., description="Current download lifecycle state")
    mime_type: str | None = Field(default=None, max_length=256, description="MIME type")
    can_resume: bool | None = Field(
        default=None,
        description="For failed downloads: the browser can resume it without starting over",
    )


class SamplePayload(BaseModel):
    """Payload sent by the browser extension or PC client to POST /v1/samples."""
    model_config = ConfigDict(extra="ignore")

    pairing_id: str = Field(..., min_length=1, max_length=128, description="Pairing identifier")
    source: str = Field(default="chrome", max_length=64, description="Source identifier")
    pc_name: str = Field(
        default="Desktop-PC",
        min_length=1,
        max_length=128,
        description="Client hostname/display name",
    )
    timestamp: datetime = Field(default_factory=utc_now, description="Generation timestamp")
    downloads: list[SourceDownloadItem] = Field(
        default_factory=list,
        max_length=100,
        description="Active downloads batch",
    )


class EvaluatedDownloadItem(BaseModel):
    """Enriched download item with speed smoothing, ETA, and progress percentage."""
    id: str
    filename: str
    percentage: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="0.0 to 100.0 or null",
    )
    speed: int = Field(default=0, ge=0, description="Smoothed bytes per second (EMA)")
    eta_seconds: int | None = Field(default=None, ge=0, description="Estimated seconds remaining")
    state: DownloadState
    bytes_downloaded: int = Field(..., ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    mime_type: str | None = None
    can_resume: bool | None = None


class PushPayload(BaseModel):
    """Payload delivered to Notifier backends (Console, FCM, LAN WebSocket)."""
    seq: int = Field(..., ge=1, description="Incrementing sequence number per pairing")
    epoch: int = Field(
        default=0,
        ge=0,
        description="Server boot time (ms). seq restarts at 1 whenever epoch changes",
    )
    sent_at: datetime = Field(default_factory=utc_now, description="Server dispatch timestamp")
    source: str = Field(default="chrome")
    pc_name: str = Field(default="Desktop-PC")
    pairing_id: str = Field(...)
    downloads: list[EvaluatedDownloadItem] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    timestamp: datetime = Field(default_factory=utc_now)


class CommandAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    RESTART = "restart"


class CommandErrorCode(StrEnum):
    """Why a command failed. A fixed set, so nothing free-form ever reaches the phone."""
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    NOT_RESUMABLE = "not_resumable"
    UNSUPPORTED_URL = "unsupported_url"
    BROWSER_ERROR = "browser_error"
    # Server-generated: the PC did not pick the command up before it expired
    EXPIRED = "expired"


# Source download IDs as they appear in samples (Chromium browsers use integers)
DOWNLOAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
COMMAND_ID_PATTERN = r"^[0-9a-f]{32}$"


class DownloadCommand(BaseModel):
    """A phone-issued action waiting to be executed by the extension."""
    command_id: str
    download_id: str
    action: CommandAction
    issued_at: datetime = Field(default_factory=utc_now)


class SampleResponse(BaseModel):
    status: str = "ok"
    processed: int
    pairing_id: str
    # Pending phone commands, handed over (and removed from the queue) with this response
    commands: list[DownloadCommand] = Field(default_factory=list)


class CreateCommandRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    download_id: str = Field(..., pattern=DOWNLOAD_ID_PATTERN)
    action: CommandAction


class CreateCommandResponse(BaseModel):
    status: str = "queued"
    command: DownloadCommand
    expires_in_sec: int
    # Seconds since the extension last fetched commands or sent a sample; null if never seen
    # since the server started. Lets the phone warn that the PC may be offline.
    pc_last_seen_sec: int | None = None


class PendingCommandsResponse(BaseModel):
    commands: list[DownloadCommand] = Field(default_factory=list)


class CommandResultRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    download_id: str = Field(..., pattern=DOWNLOAD_ID_PATTERN)
    action: CommandAction
    ok: bool
    error: CommandErrorCode | None = None


class CommandResultEvent(BaseModel):
    """Outcome of a command, pushed to the phone (only failures are pushed today)."""
    pairing_id: str
    command_id: str
    download_id: str
    action: CommandAction
    ok: bool
    error: CommandErrorCode | None = None


class CreatePairingRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pc_name: str = Field(
        default="Desktop-PC",
        min_length=1,
        max_length=128,
        description="Client hostname/display name",
    )


class CreatePairingResponse(BaseModel):
    pairing_id: str
    code: str
    secret: str
    expires_at: datetime


class ClaimPairingRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fcm_token: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Firebase Cloud Messaging device token",
    )


class ClaimPairingResponse(BaseModel):
    status: str = "ok"
    pairing_id: str
    pc_name: str
    device_secret: str = Field(
        ...,
        description="Bearer credential for the phone (token refresh, unpair). Shown once.",
    )


class PairingStatusResponse(BaseModel):
    pairing_id: str
    is_claimed: bool
    pc_name: str
    created_at: datetime
    claimed_at: datetime | None = None


class UpdateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fcm_token: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="New FCM device registration token",
    )


class UpdateTokenResponse(BaseModel):
    status: str = "ok"
    pairing_id: str


class RotateSecretResponse(BaseModel):
    status: str = "ok"
    pairing_id: str
    new_secret: str
