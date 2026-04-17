"""
Subprocess worker transport for the supervisor.

This is the missing production bridge for the v2 supervisor: spawn the worker
process, host the Unix-domain socket it connects back to, forward worker
messages to the caller, and provide a clean shutdown path.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .. import ipc as ipc_module
from . import WorkerFactory, WorkerHandle

logger = logging.getLogger(__name__)

MessageHandler = Callable[[ipc_module._IpcBase], Awaitable[None]]


@dataclass(frozen=True)
class WorkerProcessConfig:
    """Runtime parameters passed to the worker subprocess."""

    backend: str
    drone_ip: str
    telemetry_fps: int
    video_fps: int
    srt_port: int
    klv_port: int
    heartbeat_interval: float
    video_stats_interval: int
    connect_retry_interval: float
    log_level: str

    def argv(self, socket_path: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "parrot_forwarder.forwarder.worker",
            "--socket",
            str(socket_path),
            "--backend",
            self.backend,
            "--drone-ip",
            self.drone_ip,
            "--telemetry-fps",
            str(self.telemetry_fps),
            "--video-fps",
            str(self.video_fps),
            "--srt-port",
            str(self.srt_port),
            "--klv-port",
            str(self.klv_port),
            "--heartbeat-interval",
            str(self.heartbeat_interval),
            "--video-stats-interval",
            str(self.video_stats_interval),
            "--connect-retry-interval",
            str(self.connect_retry_interval),
            "--log-level",
            self.log_level,
        ]


def build_subprocess_worker_factory(
    process_config: WorkerProcessConfig,
    *,
    on_message: MessageHandler,
) -> WorkerFactory:
    """Create a ``WorkerFactory`` that spawns the real subprocess worker."""

    async def _factory(_supervisor: object) -> WorkerHandle:
        runtime_dir = Path(tempfile.mkdtemp(prefix="pf-worker-"))
        socket_path = runtime_dir / "worker.sock"
        loop = asyncio.get_running_loop()
        connected: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
            loop.create_future()
        )
        exited: asyncio.Future[int] = loop.create_future()

        server: asyncio.Server | None = None
        writer_ref: asyncio.StreamWriter | None = None
        closed = False

        async def _cleanup() -> None:
            nonlocal server, writer_ref
            if writer_ref is not None:
                with suppress(Exception):
                    writer_ref.close()
                    await writer_ref.wait_closed()
                writer_ref = None
            if server is not None:
                server.close()
                with suppress(Exception):
                    await server.wait_closed()
                server = None
            with suppress(FileNotFoundError):
                socket_path.unlink()
            shutil.rmtree(runtime_dir, ignore_errors=True)

        async def _handle_client(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            nonlocal writer_ref
            if writer_ref is not None:
                writer.close()
                await writer.wait_closed()
                return

            writer_ref = writer
            if not connected.done():
                connected.set_result((reader, writer))

            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    try:
                        message = ipc_module.decode(line)
                    except ipc_module.IpcError as exc:
                        logger.warning("dropping invalid worker IPC frame: %s", exc)
                        continue
                    await on_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("worker IPC reader raised")
            finally:
                if writer_ref is writer:
                    writer_ref = None
                with suppress(Exception):
                    writer.close()
                    await writer.wait_closed()

        server = await asyncio.start_unix_server(_handle_client, path=str(socket_path))
        try:
            process = await asyncio.create_subprocess_exec(
                *process_config.argv(socket_path),
                stdin=asyncio.subprocess.DEVNULL,
            )
        except Exception:
            await _cleanup()
            raise
        logger.info("spawned worker pid=%s backend=%s", process.pid, process_config.backend)

        async def _watch_process() -> None:
            try:
                code = await process.wait()
                if not exited.done():
                    exited.set_result(code)
            finally:
                await _cleanup()

        watch_task = asyncio.create_task(
            _watch_process(),
            name=f"pf-worker-watch:{process.pid}",
        )

        async def send(message: ipc_module._IpcBase) -> None:
            nonlocal writer_ref
            if writer_ref is None:
                try:
                    _, writer = await asyncio.wait_for(connected, timeout=5.0)
                except TimeoutError as exc:
                    raise RuntimeError("worker IPC socket never connected") from exc
                writer_ref = writer
            writer = writer_ref
            if writer is None:
                raise RuntimeError("worker IPC writer unavailable")
            writer.write(ipc_module.encode(message))
            await writer.drain()

        async def close() -> None:
            nonlocal closed
            if closed:
                return
            closed = True

            if process.returncode is None:
                if writer_ref is not None:
                    with suppress(Exception):
                        await send(ipc_module.StopCmd(graceful=True))
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3.0)
                    except TimeoutError:
                        process.terminate()
                else:
                    process.terminate()

            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()

            if process.returncode is not None and not exited.done():
                exited.set_result(process.returncode)
            with suppress(Exception):
                await watch_task

            await _cleanup()

        return WorkerHandle(
            pid=process.pid,
            send=send,
            close=close,
            exited=exited,
        )

    return _factory
