"""
Supervisor integration tests using a fake worker factory.

The fake worker is an in-process coroutine controlled by the test - it
lets us exercise the full Supervisor lifecycle (spawn, IPC event,
crash, restart) without spawning a subprocess. The real subprocess path
is covered by the E2E tests in T17.
"""

from __future__ import annotations

import asyncio

import pytest

from parrot_forwarder import ipc as ipc_module
from parrot_forwarder.backoff import BackoffPolicy
from parrot_forwarder.state_machine import State, UserReset, UserStop
from parrot_forwarder.supervisor import Supervisor, WorkerHandle, ipc_to_event

# ---------------------------------------------------------------------------
# Fake worker
# ---------------------------------------------------------------------------


class _FakeWorker:
    """Standin for a real worker subprocess.

    Exposes ``send_from_worker`` - what the real worker would write to
    the UDS and the supervisor would interpret.
    """

    _pid_seq = 1000

    def __init__(self, supervisor: Supervisor) -> None:
        _FakeWorker._pid_seq += 1
        self.pid = _FakeWorker._pid_seq
        self.supervisor = supervisor
        self.sent_to_worker: list[ipc_module._IpcBase] = []
        self.exited: asyncio.Future[int] = asyncio.get_event_loop().create_future()
        self.closed = False

    def handle(self) -> WorkerHandle:
        return WorkerHandle(
            pid=self.pid,
            send=self._send,
            close=self._close,
            exited=self.exited,
        )

    async def _send(self, msg: ipc_module._IpcBase) -> None:
        self.sent_to_worker.append(msg)

    async def _close(self) -> None:
        self.closed = True
        if not self.exited.done():
            self.exited.set_result(0)

    async def send_from_worker(self, msg: ipc_module._IpcBase) -> None:
        """Inject a worker-originated message into the supervisor."""
        event = ipc_to_event(msg)
        if event is not None:
            await self.supervisor.post_event(event)

    def crash(self, code: int = 137) -> None:
        if not self.exited.done():
            self.exited.set_result(code)


def _workers_factory(*, record: list[_FakeWorker]):
    async def _factory(supervisor: Supervisor) -> WorkerHandle:
        worker = _FakeWorker(supervisor)
        record.append(worker)
        return worker.handle()

    return _factory


# ---------------------------------------------------------------------------
# Fast fake sleep - asyncio.sleep(0) so we don't burn seconds in tests.
# ---------------------------------------------------------------------------


async def _instant_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_happy_path_reaches_streaming() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    # Let the supervisor process UserStart -> SpawnForwarder.
    await _wait_for(lambda: len(workers) == 1)
    worker = workers[0]
    await worker.send_from_worker(ipc_module.OlympeConnectedMsg())
    await worker.send_from_worker(ipc_module.PipelineStartedMsg())
    await _wait_for(lambda: sup.state_machine.state == State.STREAMING)

    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_supervisor_restarts_worker_after_unexpected_crash() -> None:
    workers: list[_FakeWorker] = []
    # Very aggressive backoff so restart happens promptly in test time.
    policy = BackoffPolicy(base_seconds=0.01, max_seconds=0.1, jitter_seconds=0.0)
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        backoff_policy=policy,
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    workers[0].crash(code=137)

    # Expect a second worker to be spawned via the ScheduleRestart -> UserStart path.
    await _wait_for(lambda: len(workers) == 2, timeout=2.0)
    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_user_reset_kills_current_worker_and_spawns_fresh() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    first = workers[0]
    await first.send_from_worker(ipc_module.OlympeConnectedMsg())
    await first.send_from_worker(ipc_module.PipelineStartedMsg())
    await _wait_for(lambda: sup.state_machine.state == State.STREAMING)

    await sup.post_event(UserReset(reason="test"))

    # The reset path kills the first worker (close called), then on its exit
    # the state machine schedules a fresh CONNECTING + SpawnForwarder.
    await _wait_for(lambda: first.closed)
    await _wait_for(lambda: len(workers) == 2, timeout=2.0)
    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_user_stop_halts_auto_restart() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    await sup.post_event(UserStop())
    await _wait_for(lambda: sup.state_machine.state == State.DISCONNECTED)
    # Give any spurious restart a tick to manifest.
    await asyncio.sleep(0.05)
    assert len(workers) == 1, "user_stop must not auto-restart"

    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_stop_is_safe_to_call_multiple_times() -> None:
    sup = Supervisor(
        worker_factory=_workers_factory(record=[]),
        auto_start=False,
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())
    sup.stop()
    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for(
    predicate, timeout: float = 1.0, poll: float = 0.005
) -> None:
    """Poll ``predicate`` until it returns truthy or ``timeout`` elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(poll)
    raise AssertionError(f"predicate {predicate!r} never became true within {timeout}s")


# ---------------------------------------------------------------------------
# Added for T16: scenarios called out in v2/specs/05-testing.md that the
# original fixtures did not yet cover.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_error_from_worker_triggers_restart() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    worker = workers[0]
    await worker.send_from_worker(ipc_module.OlympeConnectedMsg())
    await worker.send_from_worker(ipc_module.PipelineStartedMsg())
    await _wait_for(lambda: sup.state_machine.state == State.STREAMING)

    await worker.send_from_worker(ipc_module.PipelineErrorMsg(reason="bus"))
    # RESTARTING is transient; the cycle completes when a fresh worker spawns.
    await _wait_for(lambda: len(workers) >= 2, timeout=2.0)
    assert workers[0].closed, "original worker must be terminated"

    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_video_unavailable_from_worker_returns_to_ready_without_restart() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    worker = workers[0]
    await worker.send_from_worker(ipc_module.OlympeConnectedMsg())
    await worker.send_from_worker(ipc_module.PipelineStartedMsg())
    await _wait_for(lambda: sup.state_machine.state == State.STREAMING)

    await worker.send_from_worker(ipc_module.PipelineErrorMsg(reason="video_unavailable"))
    await _wait_for(lambda: sup.state_machine.state == State.READY)
    await asyncio.sleep(0.05)
    assert len(workers) == 1
    assert not workers[0].closed

    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_olympe_disconnect_triggers_restart_cycle() -> None:
    workers: list[_FakeWorker] = []
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    worker = workers[0]
    await worker.send_from_worker(ipc_module.OlympeConnectedMsg())
    await worker.send_from_worker(ipc_module.PipelineStartedMsg())
    await _wait_for(lambda: sup.state_machine.state == State.STREAMING)

    await worker.send_from_worker(ipc_module.OlympeDisconnectedMsg(reason="cable"))
    await _wait_for(lambda: len(workers) >= 2, timeout=2.0)
    assert workers[0].closed, "original worker must be terminated"

    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)


@pytest.mark.asyncio
async def test_consecutive_failures_trigger_growing_backoff() -> None:
    """Two crashes in a row must result in two ScheduleRestart entries with
    growing delays. We don't verify the actual sleep duration (that's
    covered by the pure backoff tests), but we do verify the state machine
    sees the failures."""
    workers: list[_FakeWorker] = []
    policy = BackoffPolicy(base_seconds=0.001, max_seconds=0.1, jitter_seconds=0.0)
    sup = Supervisor(
        worker_factory=_workers_factory(record=workers),
        backoff_policy=policy,
        sleep=_instant_sleep,
    )
    run_task = asyncio.create_task(sup.run())

    await _wait_for(lambda: len(workers) == 1)
    workers[0].crash(code=137)
    await _wait_for(lambda: len(workers) == 2)
    workers[1].crash(code=137)
    await _wait_for(lambda: len(workers) == 3)

    # consecutive_failures is now > 0, proving the backoff path fired.
    assert sup.state_machine.backoff.consecutive_failures >= 1

    sup.stop()
    await asyncio.wait_for(run_task, timeout=1.0)
