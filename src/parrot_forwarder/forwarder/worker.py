"""
Forwarder subprocess entry point.

The worker owns the hardware-facing runtime. It connects to the supervisor over
the configured Unix-domain socket, reports real lifecycle events, emits
heartbeat/telemetry frames while the controller is attached, and exits on
disconnect or pipeline failure so the supervisor can drive retries.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from .. import ipc as ipc_module
from .runtime import ForwarderRuntime, RuntimeConfig, make_runtime

logger = logging.getLogger(__name__)

_Sender: TypeAlias = Callable[[ipc_module._IpcBase], Awaitable[None]]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _run_runtime_loop(
    runtime: ForwarderRuntime,
    *,
    send: _Sender,
    stop_event: asyncio.Event,
    heartbeat_interval: float,
    telemetry_fps: int,
) -> int:
    try:
        try:
            runtime.connect()
            await send(ipc_module.OlympeConnectedMsg())
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker connect failed")
            await send(ipc_module.OlympeErrorMsg(reason=str(exc)))
            return 1

        try:
            runtime.start()
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker start failed")
            await send(ipc_module.PipelineErrorMsg(reason=str(exc)))
            return 1

        seq = 0
        pipeline_started = False
        telemetry_interval = 1.0 / max(1, telemetry_fps)
        loop = asyncio.get_running_loop()
        next_telemetry_at = loop.time()
        next_heartbeat_at = loop.time()
        latest_snapshot: dict[str, object] = {}
        while not stop_event.is_set():
            now = loop.time()
            sleep_for = max(0.0, min(next_telemetry_at, next_heartbeat_at) - now)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
                break
            except TimeoutError:
                pass

            now = loop.time()

            if now >= next_telemetry_at:
                snapshot = runtime.telemetry_snapshot()
                if snapshot:
                    latest_snapshot = snapshot
                    timestamp = snapshot.get("timestamp")
                    await send(
                        ipc_module.TelemetryMsg(
                            t=timestamp if isinstance(timestamp, str) else _utc_now_iso(),
                            payload=snapshot,
                        )
                    )
                while next_telemetry_at <= now:
                    next_telemetry_at += telemetry_interval

            if now >= next_heartbeat_at:
                if not runtime.is_connected():
                    await send(ipc_module.OlympeDisconnectedMsg(reason="connection_lost"))
                    return 1

                pipeline_running = runtime.is_pipeline_running()
                if pipeline_running and not pipeline_started:
                    await send(ipc_module.PipelineStartedMsg())
                    pipeline_started = True
                elif not pipeline_running and pipeline_started:
                    await send(ipc_module.PipelineErrorMsg(reason="video_unavailable"))
                    pipeline_started = False

                seq += 1
                await send(
                    ipc_module.HeartbeatMsg(
                        seq=seq,
                        healthy=True,
                        metrics=runtime.heartbeat_metrics(latest_snapshot),
                    )
                )
                while next_heartbeat_at <= now:
                    next_heartbeat_at += heartbeat_interval
    except Exception as exc:  # noqa: BLE001
        logger.exception("worker runtime loop raised")
        await send(ipc_module.PipelineErrorMsg(reason=str(exc)))
        return 1
    finally:
        with suppress(Exception):
            runtime.stop()
        with suppress(Exception):
            runtime.disconnect()
    return 0


async def _worker_main(
    socket_path: Path,
    *,
    backend: str,
    runtime_config: RuntimeConfig,
    heartbeat_interval: float,
) -> int:
    logger.info(
        "worker starting; socket=%s backend=%s drone_ip=%s video_ip=%s device_kind=%s",
        socket_path,
        backend,
        runtime_config.drone_ip,
        runtime_config.video_ip or runtime_config.drone_ip,
        runtime_config.device_kind,
    )
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
    except (OSError, FileNotFoundError) as exc:
        logger.error("cannot connect to supervisor socket: %s", exc)
        return 2

    async def _send(msg: ipc_module._IpcBase) -> None:
        writer.write(ipc_module.encode(msg))
        await writer.drain()

    stop_event = asyncio.Event()

    async def _read_commands() -> None:
        while not stop_event.is_set():
            line = await reader.readline()
            if not line:
                stop_event.set()
                return
            try:
                cmd = ipc_module.decode(line)
            except ipc_module.IpcError as exc:
                logger.warning("bad IPC frame from supervisor: %s", exc)
                continue
            if isinstance(cmd, ipc_module.StopCmd):
                logger.info("received stop command (graceful=%s)", cmd.graceful)
                stop_event.set()
                return

    reader_task = asyncio.create_task(_read_commands(), name="pf-worker-reader")

    try:
        runtime = make_runtime(backend=backend, config=runtime_config)
        return await _run_runtime_loop(
            runtime,
            send=_send,
            stop_event=stop_event,
            heartbeat_interval=heartbeat_interval,
            telemetry_fps=runtime_config.telemetry_fps,
        )
    finally:
        reader_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await reader_task
        with suppress(Exception):
            writer.close()
            await writer.wait_closed()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="parrot-forwarder-worker",
        description="ParrotForwarder v2 worker subprocess. Not meant to be invoked directly.",
    )
    parser.add_argument("--socket", required=True, type=Path, help="Path to supervisor UDS.")
    parser.add_argument(
        "--backend",
        choices=("real", "mock"),
        default="real",
        help="Worker runtime backend.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Deprecated alias for --backend=mock.",
    )
    parser.add_argument("--drone-ip", default="192.168.53.1")
    parser.add_argument("--video-ip", default=None)
    parser.add_argument(
        "--device-kind",
        choices=("drone", "skycontroller"),
        default="drone",
    )
    parser.add_argument("--telemetry-fps", type=int, default=30)
    parser.add_argument(
        "--include-raw-sdk-state-in-klv",
        choices=("true", "false"),
        default="false",
    )
    parser.add_argument("--video-fps", type=int, default=30)
    parser.add_argument("--srt-port", type=int, default=8890)
    parser.add_argument("--klv-port", type=int, default=12345)
    parser.add_argument("--video-stats-interval", type=int, default=30)
    parser.add_argument("--connect-retry-interval", type=float, default=2.0)
    parser.add_argument("--heartbeat-interval", type=float, default=1.0)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    if args.mock:
        args.backend = "mock"
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        return asyncio.run(
            _worker_main(
                args.socket,
                backend=args.backend,
                runtime_config=RuntimeConfig(
                    drone_ip=args.drone_ip,
                    video_ip=args.video_ip,
                    device_kind=args.device_kind,
                    telemetry_fps=args.telemetry_fps,
                    include_raw_sdk_state_in_klv=(
                        args.include_raw_sdk_state_in_klv == "true"
                    ),
                    video_fps=args.video_fps,
                    srt_port=args.srt_port,
                    klv_port=args.klv_port,
                    video_stats_interval=args.video_stats_interval,
                    connect_retry_interval=args.connect_retry_interval,
                ),
                heartbeat_interval=args.heartbeat_interval,
            )
        )
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
