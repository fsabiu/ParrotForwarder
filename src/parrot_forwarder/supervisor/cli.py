"""
CLI entry point for the v2 supervisor + dashboard.

This is the operator-facing service entry point. It loads layered config,
chooses an explicit worker backend, wires the supervisor to the worker IPC, and
serves the REST/WebSocket/dashboard surface over uvicorn.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import os
import shutil
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn

from .. import ipc as ipc_module
from ..backoff import BackoffPolicy
from ..config import Config, ConfigError, LoggingConfig, load_config
from ..logging_setup import configure_logging
from ..metrics import Metrics, register_metrics_route
from ..state_machine import Heartbeat
from . import Supervisor, WorkerHandle, ipc_to_event
from .api import create_app
from .api.stream import Broadcaster, publish_state_transition, register_stream_routes
from .health import HealthMonitor, HealthThresholds, run_health_poll_loop
from .ipc import WorkerProcessConfig, build_subprocess_worker_factory
from .recording.index import RecordingIndex
from .recording.recorder import Recorder

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("/etc/parrot-forwarder/config.yaml")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _can_run_real_worker() -> bool:
    if sys.platform != "linux":
        return False
    if importlib.util.find_spec("olympe") is None:
        return False
    if shutil.which("gst-launch-1.0") is None:
        return False
    return True


def _resolve_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    return "subprocess" if _can_run_real_worker() else "none"


def _install_event_bridge(
    supervisor: Supervisor,
    events: Broadcaster,
    metrics: Metrics | None = None,
) -> None:
    original_dispatch = supervisor._dispatch

    async def _wrapped(event: Any) -> None:
        before = supervisor.state_machine.state.value
        await original_dispatch(event)
        after = supervisor.state_machine.state.value
        if after != before:
            if metrics is not None:
                metrics.record_state_transition(
                    from_state=before,
                    to_state=after,
                    reason=type(event).__name__,
                )
            await publish_state_transition(
                events,
                from_state=before,
                to_state=after,
                reason=type(event).__name__,
                at=_utc_now_iso(),
            )

    supervisor._dispatch = _wrapped  # type: ignore[method-assign]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="parrot-forwarder-supervisor",
        description="ParrotForwarder v2 supervisor + dashboard.",
    )
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG_PATH),
        help="Path to config.yaml. Missing default path falls back to in-code defaults.",
    )
    parser.add_argument(
        "--bind",
        default=None,
        help="Override supervisor.http.bind (use 0.0.0.0 to expose to the LAN).",
    )
    parser.add_argument("--port", type=int, default=None, help="Override supervisor.http.port.")
    parser.add_argument(
        "--worker-backend",
        choices=("auto", "subprocess", "mock", "none"),
        default="auto",
        help=(
            "'auto' runs the real worker on a supported Linux host and falls back "
            "to 'none' elsewhere. 'mock' is a demo path only."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override logging.level (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Override logging.file.",
    )
    return parser.parse_args(argv)


def _load_runtime_config(args: argparse.Namespace) -> Config:
    config_path = Path(args.config) if args.config else _DEFAULT_CONFIG_PATH
    if config_path == _DEFAULT_CONFIG_PATH and not config_path.exists():
        yaml_path = None
    else:
        yaml_path = config_path

    cli_overrides: dict[str, object] = {}
    if args.bind is not None:
        cli_overrides["supervisor.http.bind"] = args.bind
    if args.port is not None:
        cli_overrides["supervisor.http.port"] = args.port
    if args.log_level is not None:
        cli_overrides["logging.level"] = args.log_level.upper()
    if args.log_file is not None:
        cli_overrides["logging.file"] = args.log_file

    return load_config(
        path=yaml_path,
        env=os.environ,
        cli_overrides=cli_overrides,
    )


def _with_telemetry_fps(config: Config, telemetry_fps: int) -> Config:
    return config.model_copy(
        update={
            "forwarder": config.forwarder.model_copy(
                update={"telemetry_fps": telemetry_fps}
            )
        }
    )


def _worker_process_config_from(config: Config, backend: str) -> WorkerProcessConfig:
    return WorkerProcessConfig(
        backend="real" if backend == "subprocess" else "mock",
        drone_ip=config.drone.ip,
        video_ip=config.drone.video_ip,
        device_kind=config.drone.device_kind,
        telemetry_fps=config.forwarder.telemetry_fps,
        video_fps=config.forwarder.video_fps,
        srt_port=config.forwarder.srt_port,
        klv_port=config.forwarder.klv_port,
        heartbeat_interval=config.supervisor.heartbeat.interval_seconds,
        video_stats_interval=30,
        connect_retry_interval=max(1.0, config.supervisor.heartbeat.interval_seconds),
        log_level=config.logging.level,
    )


def _build_message_handler(
    supervisor: Supervisor,
    *,
    telemetry: Broadcaster,
    health: HealthMonitor,
    metrics: Metrics | None = None,
    latest_metrics: dict[str, float] | None = None,
) -> Callable[[ipc_module._IpcBase], Awaitable[None]]:
    async def _handle(message: ipc_module._IpcBase) -> None:
        if isinstance(message, ipc_module.TelemetryMsg):
            await telemetry.publish({"t": message.t, "payload": message.payload})
            return

        event = ipc_to_event(message)
        if event is None:
            return

        if isinstance(message, ipc_module.HeartbeatMsg):
            assert isinstance(event, Heartbeat)
            if latest_metrics is not None:
                latest_metrics.clear()
                latest_metrics.update(message.metrics)
            if metrics is not None:
                metrics.record_heartbeat(lag_seconds=0.0, pipeline_metrics=message.metrics)
            for health_event in health.record_heartbeat(event, metrics=message.metrics):
                await supervisor.post_event(health_event)

        await supervisor.post_event(event)

    return _handle


def _none_worker_factory() -> Callable[[Supervisor], Awaitable[WorkerHandle]]:
    async def _factory(_supervisor: Supervisor) -> WorkerHandle:  # pragma: no cover
        raise RuntimeError("start disabled; set --worker-backend=subprocess on a Linux host")

    return _factory


async def _amain(args: argparse.Namespace) -> int:
    try:
        cfg = _load_runtime_config(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    current_config = cfg

    configure_logging(
        LoggingConfig(
            level=cfg.logging.level,
            format=cfg.logging.format,
            file=cfg.logging.file,
            rotation=cfg.logging.rotation,
        ),
        also_stream=True,
    )

    backend = _resolve_backend(args.worker_backend)
    if args.worker_backend == "auto" and backend == "none":
        logger.warning(
            "real worker unavailable on this host; starting idle dashboard (state stays DISCONNECTED)"
        )

    events = Broadcaster()
    telemetry = Broadcaster()
    metrics = Metrics() if cfg.metrics.enabled else None
    latest_heartbeat_metrics: dict[str, float] = {}
    health = HealthMonitor(
        thresholds=HealthThresholds(
            heartbeat_timeout_seconds=cfg.supervisor.heartbeat.timeout_seconds,
        )
    )

    if backend in {"subprocess", "mock"}:
        supervisor = Supervisor(
            worker_factory=_none_worker_factory(),
            backoff_policy=BackoffPolicy(
                base_seconds=cfg.supervisor.backoff.base_seconds,
                max_seconds=cfg.supervisor.backoff.max_seconds,
                jitter_seconds=cfg.supervisor.backoff.jitter_seconds,
            ),
            auto_start=cfg.supervisor.auto_start,
            start_enabled=True,
        )
        on_message = _build_message_handler(
            supervisor,
            telemetry=telemetry,
            health=health,
            metrics=metrics,
            latest_metrics=latest_heartbeat_metrics,
        )

        async def _worker_factory(sup: Supervisor) -> WorkerHandle:
            health.reset()
            subprocess_factory = build_subprocess_worker_factory(
                _worker_process_config_from(current_config, backend),
                on_message=on_message,
            )
            return await subprocess_factory(sup)

        supervisor.worker_factory = _worker_factory
    else:
        supervisor = Supervisor(
            worker_factory=_none_worker_factory(),
            backoff_policy=BackoffPolicy(
                base_seconds=cfg.supervisor.backoff.base_seconds,
                max_seconds=cfg.supervisor.backoff.max_seconds,
                jitter_seconds=cfg.supervisor.backoff.jitter_seconds,
            ),
            auto_start=False,
            start_enabled=False,
        )

    _install_event_bridge(supervisor, events, metrics=metrics)

    recorder: Recorder | None = None
    recording_index: RecordingIndex | None = None
    recordings_root: Path | None = None
    if cfg.recording.enabled:
        recordings_root = Path(cfg.recording.path)
        try:
            recordings_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "recordings path %s unavailable (%s); recording disabled", recordings_root, exc
            )
            recordings_root = None
        if recordings_root is not None:
            recording_index = RecordingIndex.open(recordings_root / "index.db")

            async def _recorder_event_sink(event_type: str, payload: dict[str, object]) -> None:
                await events.publish({"type": event_type, "payload": payload})

            recorder = Recorder(
                root_path=recordings_root,
                index=recording_index,
                srt_port=cfg.forwarder.srt_port,
                event_sink=_recorder_event_sink,
            )
            reconciled = recorder.reconcile_active_rows()
            if reconciled:
                logger.info(
                    "reconciled %d orphan recording row(s) at startup", len(reconciled)
                )

    def _set_telemetry_fps(telemetry_fps: int) -> Config:
        nonlocal current_config
        current_config = _with_telemetry_fps(current_config, telemetry_fps)
        logger.info("runtime telemetry_fps updated to %s Hz", telemetry_fps)
        return current_config

    app = create_app(
        supervisor,
        config=current_config,
        set_telemetry_fps=_set_telemetry_fps,
        recorder=recorder,
        recording_index=recording_index,
        recordings_root=recordings_root,
    )
    app.state.latest_heartbeat_metrics = latest_heartbeat_metrics
    if metrics is not None:
        register_metrics_route(app, metrics, path=current_config.metrics.path)
    register_stream_routes(
        app,
        events=events,
        telemetry=telemetry,
        default_telemetry_rate_hz=current_config.forwarder.telemetry_fps,
        max_telemetry_rate_hz=100,
    )

    config = uvicorn.Config(
        app,
        host=cfg.supervisor.http.bind,
        port=cfg.supervisor.http.port,
        log_level=cfg.logging.level.lower(),
        access_log=False,
        lifespan="off",
    )
    server = uvicorn.Server(config)

    supervisor_task = asyncio.create_task(supervisor.run(), name="pf-supervisor")
    health_task = asyncio.create_task(
        run_health_poll_loop(
            health,
            supervisor.post_event,
            interval_seconds=cfg.supervisor.heartbeat.interval_seconds,
        ),
        name="pf-health",
    )

    def _trigger_shutdown() -> None:
        supervisor.stop()
        server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _trigger_shutdown)
        except (NotImplementedError, ValueError):
            pass

    logger.info(
        "supervisor booting on %s:%s worker_backend=%s",
        cfg.supervisor.http.bind,
        cfg.supervisor.http.port,
        backend,
    )

    try:
        await server.serve()
    finally:
        if recorder is not None:
            try:
                await recorder.shutdown()
            except Exception:  # noqa: BLE001
                logger.exception("recorder shutdown failed")
        if recording_index is not None:
            recording_index.close()
        supervisor.stop()
        for task in (health_task, supervisor_task):
            if task is health_task and not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(supervisor_task, timeout=3.0)
        except TimeoutError:
            supervisor_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
