from __future__ import annotations

import asyncio

import pytest

from parrot_forwarder import ipc as ipc_module
from parrot_forwarder.supervisor.ipc import (
    WorkerProcessConfig,
    build_subprocess_worker_factory,
)


@pytest.mark.asyncio
async def test_subprocess_worker_factory_streams_mock_worker_events() -> None:
    messages: list[ipc_module._IpcBase] = []

    async def on_message(message: ipc_module._IpcBase) -> None:
        messages.append(message)

    factory = build_subprocess_worker_factory(
        WorkerProcessConfig(
            backend="mock",
            drone_ip="192.168.53.1",
            telemetry_fps=10,
            video_fps=30,
            srt_port=8890,
            klv_port=12345,
            heartbeat_interval=0.05,
            video_stats_interval=30,
            connect_retry_interval=1.0,
            log_level="INFO",
        ),
        on_message=on_message,
    )

    handle = await factory(None)  # type: ignore[arg-type]
    try:
        await _wait_for(
            lambda: any(isinstance(m, ipc_module.HeartbeatMsg) for m in messages),
            timeout=3.0,
        )
        assert any(isinstance(m, ipc_module.OlympeConnectedMsg) for m in messages)
        assert any(isinstance(m, ipc_module.PipelineStartedMsg) for m in messages)
        assert any(isinstance(m, ipc_module.HeartbeatMsg) for m in messages)
        assert any(isinstance(m, ipc_module.TelemetryMsg) for m in messages)
    finally:
        await handle.close()
        await asyncio.wait_for(handle.exited, timeout=3.0)


async def _wait_for(predicate, *, timeout: float, poll: float = 0.01) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(poll)
    raise AssertionError(f"predicate {predicate!r} never became true within {timeout}s")
