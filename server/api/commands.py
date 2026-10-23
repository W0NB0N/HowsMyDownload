"""Download commands: the phone asks the PC to pause, resume or restart a download.

    phone --POST /commands--> queue --(sample response | GET /commands)--> extension
    extension --POST /commands/{id}/result (failures)--> FCM "command_result" --> phone

Success needs no explicit reply: the extension samples right after acting, so the phone sees
the new state through the normal progress stream.
"""

import asyncio
import contextlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request, status

from server.auth import PairingActor, PairingActorDep, PairingRole
from server.commands.queue import CommandQueue
from server.notifier.base import BaseNotifier
from server.rate_limiter import (
    command_poll_limiter,
    command_result_limiter,
    command_send_limiter,
    raise_if_limited,
)
from server.schemas import (
    COMMAND_ID_PATTERN,
    CommandErrorCode,
    CommandResultEvent,
    CommandResultRequest,
    CreateCommandRequest,
    CreateCommandResponse,
    PendingCommandsResponse,
)
from server.store.base import BasePairingStore

logger = logging.getLogger("notifs.api.commands")

router = APIRouter(prefix="/v1/pairings", tags=["Commands"])

EXPIRY_SWEEP_INTERVAL_SEC = 5.0


def get_command_queue(request: Request) -> CommandQueue:
    return request.app.state.command_queue


CommandQueueDep = Annotated[CommandQueue, Depends(get_command_queue)]
CommandIdPath = Annotated[str, Path(pattern=COMMAND_ID_PATTERN)]


def _require_role(actor: PairingActor, role: PairingRole, detail: str) -> None:
    if actor.role != role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.post(
    "/{pairing_id}/commands",
    response_model=CreateCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_command(
    payload: CreateCommandRequest,
    actor: PairingActorDep,
    queue: CommandQueueDep,
) -> CreateCommandResponse:
    """Queues a command for the extension. Only the paired phone may issue commands."""
    _require_role(actor, PairingRole.DEVICE, "Only the paired device may send commands")
    pairing_id = actor.record.pairing_id
    raise_if_limited(command_send_limiter, pairing_id)

    command = queue.enqueue(pairing_id, payload.download_id, payload.action)
    logger.info("Command %s queued for %s: %s download %s",
                command.command_id[:8], pairing_id, command.action.value, command.download_id)
    return CreateCommandResponse(
        command=command,
        expires_in_sec=int(queue.ttl_sec),
        pc_last_seen_sec=queue.seconds_since_seen(pairing_id),
    )


@router.get("/{pairing_id}/commands", response_model=PendingCommandsResponse)
async def collect_commands(
    actor: PairingActorDep,
    queue: CommandQueueDep,
) -> PendingCommandsResponse:
    """Hands pending commands to the extension (and removes them from the queue)."""
    _require_role(actor, PairingRole.EXTENSION, "Only the extension may collect commands")
    pairing_id = actor.record.pairing_id
    raise_if_limited(command_poll_limiter, pairing_id)
    return PendingCommandsResponse(commands=queue.drain(pairing_id))


@router.post("/{pairing_id}/commands/{command_id}/result")
async def report_command_result(
    command_id: CommandIdPath,
    payload: CommandResultRequest,
    actor: PairingActorDep,
    request: Request,
) -> dict:
    """The extension reports a command outcome; failures are forwarded to the phone."""
    _require_role(actor, PairingRole.EXTENSION, "Only the extension may report results")
    raise_if_limited(command_result_limiter, actor.record.pairing_id)

    event = CommandResultEvent(
        pairing_id=actor.record.pairing_id,
        command_id=command_id,
        download_id=payload.download_id,
        action=payload.action,
        ok=payload.ok,
        error=None if payload.ok else (payload.error or CommandErrorCode.BROWSER_ERROR),
    )
    logger.info("Command %s result for %s: %s", command_id[:8], event.pairing_id,
                "ok" if event.ok else event.error)
    if not event.ok:
        notifier: BaseNotifier | None = getattr(request.app.state, "notifier", None)
        if notifier is not None:
            with contextlib.suppress(Exception):
                await notifier.send_command_result(actor.record.fcm_token, event)
    return {"status": "ok"}


async def notify_expired_commands(
    queue: CommandQueue,
    store: BasePairingStore,
    notifier: BaseNotifier,
) -> int:
    """Tells phones about commands their PC never collected. Returns how many expired."""
    expired = queue.pop_expired()
    for pairing_id, command in expired:
        record = await store.get_pairing(pairing_id)
        if record is None or not record.is_usable or not record.fcm_token:
            continue
        logger.info("Command %s for %s expired uncollected", command.command_id[:8], pairing_id)
        await notifier.send_command_result(
            record.fcm_token,
            CommandResultEvent(
                pairing_id=pairing_id,
                command_id=command.command_id,
                download_id=command.download_id,
                action=command.action,
                ok=False,
                error=CommandErrorCode.EXPIRED,
            ),
        )
    return len(expired)


async def run_expiry_sweeper(app: FastAPI, interval_sec: float = EXPIRY_SWEEP_INTERVAL_SEC):
    """Background task started by the app lifespan."""
    while True:
        await asyncio.sleep(interval_sec)
        try:
            await notify_expired_commands(
                app.state.command_queue, app.state.pairing_store, app.state.notifier
            )
        except Exception:
            logger.exception("Command expiry sweep failed")
