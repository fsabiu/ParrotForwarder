"""
Shared IPC schemas between supervisor and forwarder subprocess.

Wire format: newline-delimited JSON, one :class:`IpcMessage` per line.
The supervisor and the worker import the same pydantic models from this
module so the protocol stays in lockstep.

Discriminated union on ``kind`` - pydantic v2 routes to the concrete
subclass via :class:`typing.Literal`. Adding a new message type requires
adding a class AND adding it to :data:`IpcMessage` below.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class _IpcBase(BaseModel):
    """Private base class - every concrete message inherits here."""

    model_config = _FROZEN


# ---------------------------------------------------------------------------
# Worker -> Supervisor
# ---------------------------------------------------------------------------


class OlympeConnectedMsg(_IpcBase):
    kind: Literal["olympe.connected"] = "olympe.connected"


class OlympeDisconnectedMsg(_IpcBase):
    kind: Literal["olympe.disconnected"] = "olympe.disconnected"
    reason: str = ""


class OlympeErrorMsg(_IpcBase):
    kind: Literal["olympe.error"] = "olympe.error"
    reason: str


class PipelineStartedMsg(_IpcBase):
    kind: Literal["pipeline.started"] = "pipeline.started"


class PipelineEosMsg(_IpcBase):
    kind: Literal["pipeline.eos"] = "pipeline.eos"


class PipelineErrorMsg(_IpcBase):
    kind: Literal["pipeline.error"] = "pipeline.error"
    reason: str


class HeartbeatMsg(_IpcBase):
    kind: Literal["heartbeat"] = "heartbeat"
    seq: int
    healthy: bool = True
    # Opaque bag of metrics the supervisor fans out to Prometheus. Keep it
    # small - frequent and JSON-encoded.
    metrics: dict[str, float] = Field(default_factory=dict)


class TelemetryMsg(_IpcBase):
    """Single telemetry sample forwarded from the worker.

    The supervisor rate-limits this to the dashboard's WebSocket. Shape
    mirrors ``v2/architecture/api-contract.md#stream-telemetry``.
    """

    kind: Literal["telemetry"] = "telemetry"
    t: str  # ISO8601 timestamp from the worker
    payload: dict[str, object]


# ---------------------------------------------------------------------------
# Supervisor -> Worker
# ---------------------------------------------------------------------------


class StopCmd(_IpcBase):
    kind: Literal["stop"] = "stop"
    #: Whether the worker should signal Olympe to disconnect gracefully.
    graceful: bool = True


class SetTelemetryRateCmd(_IpcBase):
    kind: Literal["set_telemetry_rate"] = "set_telemetry_rate"
    hz: int = Field(ge=1, le=100)


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------


IpcMessage = Annotated[
    OlympeConnectedMsg | OlympeDisconnectedMsg | OlympeErrorMsg | PipelineStartedMsg | PipelineEosMsg | PipelineErrorMsg | HeartbeatMsg | TelemetryMsg | StopCmd | SetTelemetryRateCmd,
    Field(discriminator="kind"),
]


_MESSAGE_ADAPTER: TypeAdapter[IpcMessage] = TypeAdapter(IpcMessage)


class IpcError(Exception):
    """Raised for any IPC parsing / validation failure."""


def encode(message: _IpcBase) -> bytes:
    """Serialize ``message`` as a single newline-terminated JSON line."""
    data = message.model_dump(mode="json")
    # Keys in a stable order so tests and hexdumps stay readable.
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes | str) -> _IpcBase:
    """Parse a single newline-delimited JSON frame.

    Raises:
        IpcError: on any JSON or schema failure. The message always
            includes the offending field path when applicable.
    """
    if isinstance(line, bytes):
        text = line.decode("utf-8").rstrip("\n")
    else:
        text = line.rstrip("\n")
    if not text:
        raise IpcError("empty IPC frame")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IpcError(f"invalid JSON frame: {exc}") from exc
    try:
        return _MESSAGE_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        raise IpcError(f"schema violation at '{loc}': {first.get('msg')}") from exc
