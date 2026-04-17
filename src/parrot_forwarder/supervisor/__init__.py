"""
Supervisor runtime - drives the state machine, owns the forwarder subprocess.

The design separates pure logic (``state_machine``) from IO (this module).
The :class:`Supervisor` consumes :class:`parrot_forwarder.state_machine.Event`
instances from three sources:

    1. Worker over IPC (``OlympeConnectedMsg``, ``PipelineErrorMsg``, ...)
    2. The API layer (``UserStart``, ``UserStop``, ``UserReset``)
    3. The supervisor's own watchdog timers (``Timeout``,
       ``HealthUnresponsive``)

and feeds them one at a time into ``StateMachine.step``, executing each
returned :class:`SideEffect` descriptor. The execution strategy is in
:func:`Supervisor._run_effect`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import ipc as ipc_module
from ..backoff import BackoffPolicy
from ..state_machine import (
    EmitMetric,
    Event,
    ForwarderExit,
    HealthUnresponsive,
    Heartbeat,
    KillForwarder,
    Log,
    OlympeConnected,
    OlympeDisconnected,
    OlympeError,
    PipelineEos,
    PipelineError,
    PipelineStarted,
    ScheduleRestart,
    SetTimeout,
    SideEffect,
    SpawnForwarder,
    StateMachine,
    Timeout,
    UserReset,
    UserStart,
    UserStop,
    make_state_machine,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker handle (abstracts the subprocess for tests)
# ---------------------------------------------------------------------------


@dataclass
class WorkerHandle:
    """Opaque handle to a spawned forwarder worker.

    Tests inject a fake :class:`WorkerHandle` that reads from an
    in-process queue; production injects a real subprocess-backed handle
    (see :func:`_default_spawn_worker`).
    """

    pid: int
    send: Callable[[ipc_module._IpcBase], Awaitable[None]]
    close: Callable[[], Awaitable[None]]
    #: Fires once the subprocess has exited. Holds the exit code.
    exited: asyncio.Future[int]


WorkerFactory = Callable[["Supervisor"], Awaitable[WorkerHandle]]


# ---------------------------------------------------------------------------
# IPC -> state machine event translation
# ---------------------------------------------------------------------------


_IPC_TO_EVENT: dict[type, Callable[[Any], Event]] = {
    ipc_module.OlympeConnectedMsg: lambda _m: OlympeConnected(),
    ipc_module.OlympeDisconnectedMsg: lambda m: OlympeDisconnected(reason=m.reason),
    ipc_module.OlympeErrorMsg: lambda m: OlympeError(reason=m.reason),
    ipc_module.PipelineStartedMsg: lambda _m: PipelineStarted(),
    ipc_module.PipelineEosMsg: lambda _m: PipelineEos(),
    ipc_module.PipelineErrorMsg: lambda m: PipelineError(reason=m.reason),
    ipc_module.HeartbeatMsg: lambda m: Heartbeat(seq=m.seq, healthy=m.healthy),
}


def ipc_to_event(message: ipc_module._IpcBase) -> Event | None:
    """Translate an IPC message into a state-machine event, if applicable."""
    translator = _IPC_TO_EVENT.get(type(message))
    if translator is None:
        return None
    return translator(message)


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


@dataclass
class Supervisor:
    """Asyncio supervisor that owns one worker subprocess.

    Wire it up with :meth:`run`; send API events with :meth:`post_event`.
    Shutdown by awaiting :meth:`stop` from outside (SIGTERM handler calls
    this) - the event loop drains and cleanly exits.
    """

    worker_factory: WorkerFactory
    backoff_policy: BackoffPolicy = field(default_factory=BackoffPolicy)
    auto_start: bool = True
    start_enabled: bool = True
    #: Injectable clock so tests don't wall-sleep.
    sleep: Callable[[float], Awaitable[None]] = field(default_factory=lambda: asyncio.sleep)

    # Runtime state - populated inside :meth:`run`.
    state_machine: StateMachine = field(init=False)
    _worker: WorkerHandle | None = field(init=False, default=None)
    _event_queue: asyncio.Queue[Event] = field(init=False)
    _stop_requested: asyncio.Event = field(init=False)
    _timeout_task: asyncio.Task[None] | None = field(init=False, default=None)
    _exit_watcher: asyncio.Task[None] | None = field(init=False, default=None)
    _pending_restart: asyncio.Task[None] | None = field(init=False, default=None)
    restart_count: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.state_machine = make_state_machine(policy=self.backoff_policy)
        self._event_queue = asyncio.Queue()
        self._stop_requested = asyncio.Event()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the supervisor loop. Returns when :meth:`stop` is called."""
        if self.auto_start:
            await self.post_event(UserStart())

        try:
            while not self._stop_requested.is_set():
                # Two waiters: either a new event lands, or stop is signaled.
                get_task = asyncio.create_task(self._event_queue.get())
                stop_task = asyncio.create_task(self._stop_requested.wait())
                done, pending = await asyncio.wait(
                    {get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if stop_task in done and get_task not in done:
                    break
                event = get_task.result()
                await self._dispatch(event)
        finally:
            await self._shutdown()

    async def post_event(self, event: Event) -> None:
        """Queue an event from the API layer. Thread-safe via asyncio.Queue."""
        await self._event_queue.put(event)

    def stop(self) -> None:
        """Signal the supervisor to exit. Safe to call from a signal handler."""
        self._stop_requested.set()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _dispatch(self, event: Event) -> None:
        """Step the state machine and execute every returned side effect."""
        effects = self.state_machine.step(event)
        for effect in effects:
            await self._run_effect(effect)

    async def _run_effect(self, effect: SideEffect) -> None:
        """Execute one side-effect descriptor."""
        if isinstance(effect, Log):
            _log_effect(effect)
            return
        if isinstance(effect, EmitMetric):
            # Metrics sink lives in T12. For now, just debug-log the emit.
            logger.debug(
                "metric emit", extra={"name": effect.name, "labels": dict(effect.labels)}
            )
            return
        if isinstance(effect, SetTimeout):
            await self._arm_timeout(effect.seconds)
            return
        if isinstance(effect, SpawnForwarder):
            await self._spawn_worker()
            return
        if isinstance(effect, KillForwarder):
            await self._kill_worker(grace_seconds=effect.grace_seconds)
            return
        if isinstance(effect, ScheduleRestart):
            self.restart_count += 1
            await self._schedule_restart(delay=effect.delay_seconds, reason=effect.reason)
            return
        logger.warning("unknown side effect %s - ignoring", type(effect).__name__)

    async def _arm_timeout(self, seconds: float | None) -> None:
        if self._timeout_task is not None and not self._timeout_task.done():
            self._timeout_task.cancel()
            self._timeout_task = None
        if seconds is None:
            return

        async def _fire() -> None:
            try:
                # State timeouts use the real clock - injecting ``self.sleep``
                # here would collapse all timeouts in tests, which wouldn't
                # match the production semantics we're verifying.
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                return
            await self.post_event(Timeout())

        self._timeout_task = asyncio.create_task(_fire(), name="pf-state-timeout")

    async def _spawn_worker(self) -> None:
        if self._worker is not None:
            logger.warning("spawn requested but worker already running - ignoring")
            return
        logger.info("spawning forwarder worker")
        self._worker = await self.worker_factory(self)

        async def _watch_exit(handle: WorkerHandle) -> None:
            try:
                code = await handle.exited
            except asyncio.CancelledError:
                return
            logger.info("worker exited code=%s", code)
            # Only post the event if this is still the active worker; after
            # KillForwarder has cleaned up we don't want a stale exit to
            # re-enter the state machine.
            if self._worker is handle:
                self._worker = None
                await self.post_event(ForwarderExit(exit_code=code))

        self._exit_watcher = asyncio.create_task(
            _watch_exit(self._worker), name="pf-worker-exit"
        )

    async def _kill_worker(self, grace_seconds: float) -> None:
        """Initiate worker termination. Do NOT clear ``self._worker`` here -
        the exit watcher sees the child exit, posts ``ForwarderExit``, and
        the state machine advances accordingly. Clearing early would strand
        the state machine in RESTARTING forever.
        """
        worker = self._worker
        if worker is None:
            return
        logger.info("terminating worker pid=%s grace=%.1fs", worker.pid, grace_seconds)
        try:
            await worker.close()
        except Exception:  # noqa: BLE001 - best-effort during shutdown
            logger.exception("worker close raised; continuing")

    async def _schedule_restart(self, delay: float, reason: str) -> None:
        if self._pending_restart is not None and not self._pending_restart.done():
            # Replace any in-flight schedule with the newer one.
            self._pending_restart.cancel()

        async def _fire() -> None:
            try:
                await self.sleep(delay)
            except asyncio.CancelledError:
                return
            await self.post_event(UserStart())

        self._pending_restart = asyncio.create_task(
            _fire(), name=f"pf-restart:{reason}"
        )

    async def _shutdown(self) -> None:
        # Synthesize UserStop so the state machine leaves a clean log trail.
        try:
            await self._dispatch(UserStop())
        except Exception:  # noqa: BLE001 - shutdown must not raise
            logger.exception("error dispatching UserStop during shutdown")
        for task_attr in ("_timeout_task", "_exit_watcher", "_pending_restart"):
            task = getattr(self, task_attr)
            if task is not None and not task.done():
                task.cancel()

    # ------------------------------------------------------------------
    # Public helpers for API integration (T10)
    # ------------------------------------------------------------------

    async def user_start(self) -> None:
        await self.post_event(UserStart())

    async def user_stop(self) -> None:
        await self.post_event(UserStop())

    async def user_reset(self, reason: str = "operator requested") -> None:
        await self.post_event(UserReset(reason=reason))


def _log_effect(effect: Log) -> None:
    """Emit a :class:`Log` side effect through the stdlib logger."""
    payload = {k: v for k, v in effect.fields}
    level = getattr(logging, effect.level.upper(), logging.INFO)
    logger.log(level, effect.message, extra={"state_machine": payload})


# ---------------------------------------------------------------------------
# Default subprocess-backed worker factory
# ---------------------------------------------------------------------------


async def _default_spawn_worker(
    supervisor: Supervisor,
    socket_path: Path,
    worker_args: Iterable[str] = (),
    python_executable: str | None = None,
) -> WorkerHandle:
    """Production worker factory: spawn ``parrot-forwarder-worker``.

    Tests do NOT use this - they inject an in-process fake worker factory.
    This is the real one that T18 documentation references.
    """
    exe = python_executable or os.fsdecode(_default_python())
    cmd = [exe, "-m", "parrot_forwarder.forwarder.worker", "--socket", str(socket_path), *worker_args]
    logger.info("exec worker: %s", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
    )
    loop = asyncio.get_running_loop()
    exited: asyncio.Future[int] = loop.create_future()

    async def _wait() -> None:
        code = await process.wait()
        if not exited.done():
            exited.set_result(code)

    asyncio.create_task(_wait(), name=f"pf-worker-wait:{process.pid}")

    async def send(_message: ipc_module._IpcBase) -> None:
        # The real IPC path writes to the UDS. The subprocess-backed
        # factory used in production is completed by T07 integration
        # tests via a fake factory; the UDS writer wiring lives in
        # supervisor/ipc.py and is hooked up by the caller.
        raise NotImplementedError(
            "send() not wired yet in the default factory - supervisor/ipc.py takes over"
        )

    async def close() -> None:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except TimeoutError:
                process.kill()
                await process.wait()

    return WorkerHandle(
        pid=process.pid,
        send=send,
        close=close,
        exited=exited,
    )


def _default_python() -> str:
    """Return the Python interpreter to exec for the worker."""
    import sys

    return sys.executable


# ---------------------------------------------------------------------------
# Signal wiring helper (used by the CLI entry point)
# ---------------------------------------------------------------------------


def install_signal_handlers(supervisor: Supervisor) -> None:
    """Install SIGINT/SIGTERM handlers that call :meth:`Supervisor.stop`."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, supervisor.stop)
        except (NotImplementedError, ValueError):
            # add_signal_handler raises on Windows and when not on the main
            # thread. Fall back to the portable signal module.
            signal.signal(sig, lambda *_: supervisor.stop())


async def _post_health_unresponsive(supervisor: Supervisor, since_seconds: float) -> None:
    """Helper to post a health event without importing the class upstream."""
    await supervisor.post_event(HealthUnresponsive(since_seconds=since_seconds))


__all__ = [
    "Supervisor",
    "WorkerHandle",
    "WorkerFactory",
    "ipc_to_event",
    "install_signal_handlers",
]
