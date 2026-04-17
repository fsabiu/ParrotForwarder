"""
CLI entry point for the v2 supervisor + dashboard.

Registered as the ``parrot-forwarder-supervisor`` console script. It
starts the asyncio :class:`Supervisor` with a worker factory you choose
on the command line, then serves the REST + WebSocket + dashboard
surface via uvicorn on the same event loop.

For now the default ``--worker-backend=mock`` keeps everything
in-process (MockDrone wrapped in a small stand-in worker) so the
dashboard works out of the box without a drone. ``--worker-backend=none``
starts the supervisor with ``auto_start=False`` so the dashboard shows
``DISCONNECTED`` until the operator clicks **Start**.
``--worker-backend=subprocess`` is reserved for the real Olympe worker
once T17 lands.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import uvicorn

from .. import ipc as ipc_module
from ..backoff import BackoffPolicy
from ..config import LoggingConfig
from ..logging_setup import configure_logging
from . import Supervisor, WorkerHandle
from .api import create_app
from .api.stream import (
    Broadcaster,
    publish_state_transition,
    register_stream_routes,
)
from .health import HealthMonitor, HealthThresholds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fake in-process worker (for the mock backend)
# ---------------------------------------------------------------------------


@dataclass
class _MockWorker:
    """A small stand-in worker used when ``--worker-backend=mock``.

    It immediately emits the happy-path events (``olympe.connected`` ->
    ``pipeline.started``), then heartbeats every second until the
    supervisor closes it. Purpose: make the dashboard light up green
    without any drone or subprocess so Francesco can verify the plumbing
    end-to-end.
    """

    supervisor: Supervisor
    pid: int
    exited: asyncio.Future[int]
    _task: asyncio.Task[None] | None = None
    _stopped: bool = False

    def handle(self) -> WorkerHandle:
        async def send(_m: ipc_module._IpcBase) -> None:
            # Mock worker ignores commands; close() is how the supervisor
            # stops it.
            return None

        async def close() -> None:
            self._stopped = True
            if self._task is not None and not self._task.done():
                self._task.cancel()
            if not self.exited.done():
                self.exited.set_result(0)

        return WorkerHandle(pid=self.pid, send=send, close=close, exited=self.exited)

    async def start(self) -> None:
        """Run the happy-path event sequence against the supervisor."""
        # Tiny pause so the supervisor's CONNECTING state is visible on
        # the dashboard instead of flashing through instantly.
        await asyncio.sleep(0.2)
        if self._stopped:
            return
        from ..state_machine import Heartbeat, OlympeConnected, PipelineStarted

        await self.supervisor.post_event(OlympeConnected())
        await asyncio.sleep(0.1)
        if self._stopped:
            return
        await self.supervisor.post_event(PipelineStarted())
        seq = 0
        while not self._stopped:
            await asyncio.sleep(1.0)
            if self._stopped:
                return
            seq += 1
            await self.supervisor.post_event(Heartbeat(seq=seq, healthy=True))


_pid_seq = 10_000


def _mock_worker_factory() -> Callable[[Supervisor], Awaitable[WorkerHandle]]:
    """Build a factory that produces in-process mock workers."""

    async def _factory(supervisor: Supervisor) -> WorkerHandle:
        global _pid_seq
        _pid_seq += 1
        loop = asyncio.get_running_loop()
        exited: asyncio.Future[int] = loop.create_future()
        worker = _MockWorker(supervisor=supervisor, pid=_pid_seq, exited=exited)
        worker._task = asyncio.create_task(worker.start(), name="pf-mock-worker")
        return worker.handle()

    return _factory


# ---------------------------------------------------------------------------
# Event bridge: supervisor state machine -> WebSocket broadcasters
# ---------------------------------------------------------------------------


def _install_event_bridge(
    supervisor: Supervisor,
    events: Broadcaster,
) -> None:
    """Wrap the supervisor's dispatcher so every transition / restart
    side effect is also published to the ``/stream/events`` broadcaster.
    The full metrics bridge is T12 follow-up; this is enough to make
    the dashboard show real transitions in the event log.
    """
    original_dispatch = supervisor._dispatch

    async def _wrapped(event: Any) -> None:
        before = supervisor.state_machine.state.value
        await original_dispatch(event)
        after = supervisor.state_machine.state.value
        if after != before:
            await publish_state_transition(
                events,
                from_state=before,
                to_state=after,
                reason=type(event).__name__,
                at=_utc_now_iso(),
            )

    supervisor._dispatch = _wrapped  # type: ignore[method-assign]


def _utc_now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="parrot-forwarder-supervisor",
        description="ParrotForwarder v2 supervisor + dashboard.",
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="HTTP bind address (use 0.0.0.0 to expose to the LAN).",
    )
    parser.add_argument("--port", type=int, default=8080, help="HTTP port.")
    parser.add_argument(
        "--worker-backend",
        choices=("mock", "none"),
        default="mock",
        help=(
            "Which worker backend to use. 'mock' runs an in-process stand-in "
            "that walks the happy path (useful without a drone); 'none' starts "
            "the supervisor idle (dashboard shows DISCONNECTED until you "
            "click Start)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Root log level (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--log-file",
        default="/tmp/parrot-forwarder.log",
        help="Path to the rotating JSON log file.",
    )
    return parser.parse_args(argv)


async def _amain(args: argparse.Namespace) -> int:
    configure_logging(
        LoggingConfig(level=args.log_level.upper(), format="json", file=args.log_file),
        also_stream=True,
    )
    logger.info("supervisor booting on %s:%s backend=%s", args.bind, args.port, args.worker_backend)

    # Build broadcasters before the supervisor so the bridge can reach them.
    events = Broadcaster()
    telemetry = Broadcaster()

    if args.worker_backend == "mock":
        worker_factory = _mock_worker_factory()
        auto_start = True
    else:
        # 'none' - no auto-start; waits for POST /control/start.
        async def _noop_factory(_sup: Supervisor) -> WorkerHandle:  # pragma: no cover
            raise RuntimeError("start disabled; set --worker-backend=mock to run the demo")

        worker_factory = _noop_factory
        auto_start = False

    supervisor = Supervisor(
        worker_factory=worker_factory,
        backoff_policy=BackoffPolicy(base_seconds=1.0, max_seconds=30.0, jitter_seconds=0.5),
        auto_start=auto_start,
    )
    _install_event_bridge(supervisor, events)

    health = HealthMonitor(thresholds=HealthThresholds())
    _ = health  # wiring the health poll loop into the supervisor is T12 follow-up.

    app = create_app(supervisor)
    register_stream_routes(app, events=events, telemetry=telemetry)

    config = uvicorn.Config(
        app,
        host=args.bind,
        port=args.port,
        log_level=args.log_level.lower(),
        access_log=False,
        lifespan="off",
    )
    server = uvicorn.Server(config)

    # Run supervisor + uvicorn on the same event loop; shutdown when either
    # exits.
    supervisor_task = asyncio.create_task(supervisor.run(), name="pf-supervisor")

    def _trigger_shutdown() -> None:
        supervisor.stop()
        server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _trigger_shutdown)
        except (NotImplementedError, ValueError):
            pass

    try:
        await server.serve()
    finally:
        supervisor.stop()
        try:
            await asyncio.wait_for(supervisor_task, timeout=3.0)
        except TimeoutError:
            supervisor_task.cancel()

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
