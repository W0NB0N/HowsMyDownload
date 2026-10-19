"""Pydantic schemas and data models conforming to Protocol Schema v1."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


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


class SamplePayload(BaseModel):
    """Payload sent by the Chrome extension or PC client to POST /v1/samples."""
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
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=utc_now)


class SampleResponse(BaseModel):
    status: str = "ok"
    processed: int
    pairing_id: str


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
