from __future__ import annotations

import asyncio

import pytest

from parrot_forwarder import ipc as ipc_module
from parrot_forwarder.forwarder.worker import _run_runtime_loop


class _FakeRuntime:
    def __init__(self, pipeline_states: list[bool]) -> None:
        self._pipeline_states = iter(pipeline_states)
        self._last_pipeline = False
        self.connected = True
        self.stop_called = False
        self.disconnect_called = False
        self.samples = 0

    def connect(self) -> None:
        self.connected = True

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.stop_called = True

    def disconnect(self) -> None:
        self.disconnect_called = True
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def is_pipeline_running(self) -> bool:
        try:
            self._last_pipeline = next(self._pipeline_states)
        except StopIteration:
            pass
        return self._last_pipeline

    def telemetry_snapshot(self) -> dict[str, object]:
        self.samples += 1
        return {
            "timestamp": f"2026-04-17T00:00:0{self.samples}Z",
            "battery_percent": 80,
        }

    def heartbeat_metrics(self, snapshot: dict[str, object]) -> dict[str, float]:
        return {"battery_percent": float(snapshot["battery_percent"])}


@pytest.mark.asyncio
async def test_worker_waits_for_real_pipeline_start_and_reports_video_loss() -> None:
    runtime = _FakeRuntime([False, False, True, True, False, False])
    messages: list[ipc_module._IpcBase] = []
    stop_event = asyncio.Event()
    heartbeat_count = 0

    async def send(message: ipc_module._IpcBase) -> None:
        nonlocal heartbeat_count
        messages.append(message)
        if isinstance(message, ipc_module.HeartbeatMsg):
            heartbeat_count += 1
            if heartbeat_count >= 5:
                stop_event.set()

    code = await _run_runtime_loop(
        runtime,
        send=send,
        stop_event=stop_event,
        heartbeat_interval=0.001,
        telemetry_fps=1000,
    )

    assert code == 0
    assert runtime.stop_called is True
    assert runtime.disconnect_called is True

    pipeline_started_indexes = [
        idx for idx, msg in enumerate(messages) if isinstance(msg, ipc_module.PipelineStartedMsg)
    ]
    assert len(pipeline_started_indexes) == 1
    first_heartbeat_index = next(
        idx for idx, msg in enumerate(messages) if isinstance(msg, ipc_module.HeartbeatMsg)
    )
    assert pipeline_started_indexes[0] > first_heartbeat_index

    video_errors = [
        msg
        for msg in messages
        if isinstance(msg, ipc_module.PipelineErrorMsg) and msg.reason == "video_unavailable"
    ]
    assert len(video_errors) == 1


@pytest.mark.asyncio
async def test_worker_stays_ready_while_pipeline_never_starts() -> None:
    runtime = _FakeRuntime([False, False, False, False])
    messages: list[ipc_module._IpcBase] = []
    stop_event = asyncio.Event()
    heartbeat_count = 0

    async def send(message: ipc_module._IpcBase) -> None:
        nonlocal heartbeat_count
        messages.append(message)
        if isinstance(message, ipc_module.HeartbeatMsg):
            heartbeat_count += 1
            if heartbeat_count >= 3:
                stop_event.set()

    code = await _run_runtime_loop(
        runtime,
        send=send,
        stop_event=stop_event,
        heartbeat_interval=0.001,
        telemetry_fps=1000,
    )

    assert code == 0
    assert any(isinstance(msg, ipc_module.OlympeConnectedMsg) for msg in messages)
    assert not any(isinstance(msg, ipc_module.PipelineStartedMsg) for msg in messages)


@pytest.mark.asyncio
async def test_worker_telemetry_rate_is_independent_from_heartbeat() -> None:
    runtime = _FakeRuntime([True, True])
    messages: list[ipc_module._IpcBase] = []
    stop_event = asyncio.Event()
    telemetry_count = 0
    heartbeat_count = 0

    async def send(message: ipc_module._IpcBase) -> None:
        nonlocal telemetry_count, heartbeat_count
        messages.append(message)
        if isinstance(message, ipc_module.TelemetryMsg):
            telemetry_count += 1
        if isinstance(message, ipc_module.HeartbeatMsg):
            heartbeat_count += 1
        if telemetry_count >= 5:
            stop_event.set()

    code = await _run_runtime_loop(
        runtime,
        send=send,
        stop_event=stop_event,
        heartbeat_interval=1.0,
        telemetry_fps=200,
    )

    assert code == 0
    assert telemetry_count >= 5
    assert heartbeat_count <= 1
