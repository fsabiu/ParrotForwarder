"""
IPC protocol tests - roundtrip every message type, verify schema errors
name the offending field.
"""

from __future__ import annotations

import pytest

from parrot_forwarder.ipc import (
    HeartbeatMsg,
    IpcError,
    OlympeConnectedMsg,
    OlympeDisconnectedMsg,
    OlympeErrorMsg,
    PipelineEosMsg,
    PipelineErrorMsg,
    PipelineStartedMsg,
    SetTelemetryRateCmd,
    StopCmd,
    TelemetryMsg,
    decode,
    encode,
)


@pytest.mark.parametrize(
    "message",
    [
        OlympeConnectedMsg(),
        OlympeDisconnectedMsg(reason="cable"),
        OlympeErrorMsg(reason="auth"),
        PipelineStartedMsg(),
        PipelineEosMsg(),
        PipelineErrorMsg(reason="bus"),
        HeartbeatMsg(seq=42, healthy=False, metrics={"fps": 29.97}),
        TelemetryMsg(t="2026-04-17T00:00:00Z", payload={"battery_percent": 78}),
        StopCmd(graceful=True),
        SetTelemetryRateCmd(hz=5),
    ],
)
def test_roundtrip_all_message_types(message: object) -> None:
    line = encode(message)  # type: ignore[arg-type]
    assert line.endswith(b"\n"), "frames must be newline-terminated"
    assert line.count(b"\n") == 1, "frames must contain exactly one newline"
    decoded = decode(line)
    assert decoded == message


def test_decode_rejects_empty_frame() -> None:
    with pytest.raises(IpcError, match="empty"):
        decode(b"\n")


def test_decode_rejects_malformed_json() -> None:
    with pytest.raises(IpcError, match="invalid JSON"):
        decode(b"{not json\n")


def test_decode_rejects_unknown_kind() -> None:
    with pytest.raises(IpcError):
        decode(b'{"kind": "nope"}\n')


def test_decode_rejects_missing_required_field() -> None:
    with pytest.raises(IpcError, match="reason"):
        decode(b'{"kind": "olympe.error"}\n')


def test_decode_rejects_out_of_range_rate() -> None:
    with pytest.raises(IpcError, match="hz"):
        decode(b'{"kind": "set_telemetry_rate", "hz": 0}\n')


def test_heartbeat_defaults() -> None:
    msg = HeartbeatMsg(seq=1)
    assert msg.healthy is True
    assert msg.metrics == {}


def test_encode_produces_sorted_keys() -> None:
    """Stable ordering so hexdumps and tests stay readable."""
    line = encode(OlympeDisconnectedMsg(reason="x"))
    assert line == b'{"kind":"olympe.disconnected","reason":"x"}\n'


def test_bytes_and_str_decode_equivalently() -> None:
    msg = HeartbeatMsg(seq=7)
    line = encode(msg)
    assert decode(line) == decode(line.decode())
