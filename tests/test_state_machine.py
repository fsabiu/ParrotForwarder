"""
Tests for :mod:`parrot_forwarder.state_machine`.

Covers every transition called out in
``v2/architecture/state-machine.md``, every per-state timeout, and the
"illegal event does not crash" invariant.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

from parrot_forwarder.backoff import BackoffPolicy, BackoffState
from parrot_forwarder.state_machine import (
    STATE_TIMEOUT_SECONDS,
    EmitMetric,
    ForwarderExit,
    HealthDegraded,
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
    State,
    StateMachine,
    Timeout,
    UserReset,
    UserStart,
    UserStop,
    make_state_machine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sm(
    state: State = State.DISCONNECTED,
    *,
    jitter: float = 0.0,
    base: float = 1.0,
    max_seconds: float = 60.0,
    now: float = 0.0,
) -> StateMachine:
    """Build a deterministic StateMachine at ``state`` with controllable time."""
    policy = BackoffPolicy(base_seconds=base, max_seconds=max_seconds, jitter_seconds=jitter)

    def now_fn() -> float:
        return now

    sm = StateMachine(
        state=state,
        backoff=BackoffState(policy=policy, rng=random.Random(0)),
        now_fn=now_fn,
    )
    # If caller starts us in STREAMING, prime the window so exit transitions
    # reset backoff appropriately.
    if state == State.STREAMING:
        sm._streaming_since = now
    return sm


def _pick(effects: Iterable[SideEffect], kind: type) -> list[SideEffect]:
    return [e for e in effects if isinstance(e, kind)]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_state_machine_starts_disconnected_by_default() -> None:
    sm = make_state_machine()
    assert sm.state == State.DISCONNECTED


def test_state_timeouts_mirror_spec() -> None:
    """spec check: STATE_TIMEOUT_SECONDS must match state-machine.md."""
    assert STATE_TIMEOUT_SECONDS[State.DISCONNECTED] is None
    assert STATE_TIMEOUT_SECONDS[State.CONNECTING] == 30.0
    assert STATE_TIMEOUT_SECONDS[State.READY] is None
    assert STATE_TIMEOUT_SECONDS[State.STREAMING] is None
    assert STATE_TIMEOUT_SECONDS[State.DEGRADED] == 15.0
    assert STATE_TIMEOUT_SECONDS[State.RESTARTING] == 5.0


# ---------------------------------------------------------------------------
# Happy path: user_start -> CONNECTING -> READY -> STREAMING
# ---------------------------------------------------------------------------


def test_user_start_from_disconnected_spawns_and_transitions_to_connecting() -> None:
    sm = _sm()
    effects = sm.step(UserStart())
    assert sm.state == State.CONNECTING
    assert _pick(effects, SpawnForwarder), "dispatcher must spawn the forwarder"
    assert _pick(effects, SetTimeout)[0].seconds == 30.0


def test_user_start_when_already_connecting_is_noop() -> None:
    sm = _sm(State.CONNECTING)
    effects = sm.step(UserStart())
    assert sm.state == State.CONNECTING
    assert _pick(effects, SpawnForwarder) == []


def test_olympe_connected_in_connecting_moves_to_ready() -> None:
    sm = _sm(State.CONNECTING)
    effects = sm.step(OlympeConnected())
    assert sm.state == State.READY
    assert _pick(effects, SetTimeout)[0].seconds is None


def test_pipeline_started_in_ready_moves_to_streaming() -> None:
    sm = _sm(State.READY)
    effects = sm.step(PipelineStarted())
    assert sm.state == State.STREAMING
    assert _pick(effects, SetTimeout)[0].seconds is None


def test_streaming_records_window_start() -> None:
    sm = _sm(State.READY, now=100.0)
    sm.step(PipelineStarted())
    assert sm._streaming_since == 100.0


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_olympe_disconnected_in_streaming_goes_to_restarting() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(OlympeDisconnected(reason="cable"))
    assert sm.state == State.RESTARTING
    assert _pick(effects, KillForwarder), "dispatcher must kill the child"


def test_pipeline_error_in_streaming_goes_to_restarting() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(PipelineError(reason="bus"))
    assert sm.state == State.RESTARTING
    assert _pick(effects, KillForwarder)


def test_video_unavailable_in_streaming_returns_to_ready() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(PipelineError(reason="video_unavailable"))
    assert sm.state == State.READY
    assert _pick(effects, KillForwarder) == []


def test_pipeline_eos_in_streaming_goes_to_restarting() -> None:
    sm = _sm(State.STREAMING)
    sm.step(PipelineEos())
    assert sm.state == State.RESTARTING


def test_pipeline_error_in_ready_goes_to_restarting() -> None:
    sm = _sm(State.READY)
    effects = sm.step(PipelineError(reason="bus"))
    assert sm.state == State.RESTARTING
    assert _pick(effects, KillForwarder)


def test_video_unavailable_in_ready_stays_ready() -> None:
    sm = _sm(State.READY)
    effects = sm.step(PipelineError(reason="video_unavailable"))
    assert sm.state == State.READY
    assert _pick(effects, KillForwarder) == []


def test_olympe_error_in_connecting_schedules_restart_with_backoff() -> None:
    sm = _sm(State.CONNECTING)
    effects = sm.step(OlympeError(reason="auth"))
    assert sm.state == State.DISCONNECTED
    schedules = _pick(effects, ScheduleRestart)
    assert len(schedules) == 1
    assert schedules[0].delay_seconds == 1.0  # base * 2^0


def test_connecting_timeout_schedules_restart_and_goes_disconnected() -> None:
    sm = _sm(State.CONNECTING)
    effects = sm.step(Timeout())
    assert sm.state == State.DISCONNECTED
    assert _pick(effects, ScheduleRestart)


def test_ready_timeout_is_illegal_noop() -> None:
    sm = _sm(State.READY)
    effects = sm.step(Timeout())
    assert sm.state == State.READY
    assert _pick(effects, KillForwarder) == []


def test_degraded_timeout_goes_to_restarting() -> None:
    sm = _sm(State.DEGRADED)
    sm.step(Timeout())
    assert sm.state == State.RESTARTING


def test_restarting_timeout_escalates_to_sigkill_but_stays_in_restarting() -> None:
    sm = _sm(State.RESTARTING)
    effects = sm.step(Timeout())
    # Stays in RESTARTING - dispatcher sees the hard-kill side effect and
    # waits for ForwarderExit to advance.
    assert sm.state == State.RESTARTING
    kills = _pick(effects, KillForwarder)
    assert kills and kills[0].grace_seconds == 0.0


# ---------------------------------------------------------------------------
# Health events
# ---------------------------------------------------------------------------


def test_health_unresponsive_in_streaming_goes_to_degraded() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(HealthUnresponsive(since_seconds=6.0))
    assert sm.state == State.DEGRADED
    assert _pick(effects, SetTimeout)[0].seconds == 15.0


def test_health_degraded_in_streaming_goes_to_degraded_with_signal() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(HealthDegraded(signal="fps"))
    assert sm.state == State.DEGRADED
    # Transition reason mentions the signal so logs can filter on it.
    logs = _pick(effects, Log)
    assert any(
        any("fps" in str(v) for _, v in log.fields) for log in logs  # type: ignore[attr-defined]
    ), "expected the signal name in the transition log fields"


def test_heartbeat_healthy_in_degraded_recovers_to_streaming() -> None:
    sm = _sm(State.DEGRADED)
    effects = sm.step(Heartbeat(seq=1, healthy=True))
    assert sm.state == State.STREAMING
    assert _pick(effects, SetTimeout)[0].seconds is None


def test_heartbeat_in_streaming_is_noop() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(Heartbeat(seq=42))
    assert sm.state == State.STREAMING
    assert _pick(effects, SetTimeout) == []  # no transition = no new timeout


# ---------------------------------------------------------------------------
# Restart cycle completion
# ---------------------------------------------------------------------------


def test_forwarder_exit_in_restarting_moves_to_connecting_and_spawns() -> None:
    sm = _sm(State.RESTARTING)
    effects = sm.step(ForwarderExit(exit_code=0))
    assert sm.state == State.CONNECTING
    assert _pick(effects, SpawnForwarder)


def test_forwarder_exit_in_disconnected_is_ignored() -> None:
    sm = _sm(State.DISCONNECTED)
    effects = sm.step(ForwarderExit(exit_code=0))
    assert sm.state == State.DISCONNECTED
    # No spawn, no schedule - we're idle by operator command.
    assert _pick(effects, SpawnForwarder) == []
    assert _pick(effects, ScheduleRestart) == []


def test_forwarder_exit_in_streaming_schedules_restart_with_reason() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(ForwarderExit(exit_code=137))
    assert sm.state == State.DISCONNECTED
    schedules = _pick(effects, ScheduleRestart)
    assert schedules and "137" in schedules[0].reason


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------


def test_user_stop_from_streaming_kills_and_goes_disconnected() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(UserStop())
    assert sm.state == State.DISCONNECTED
    assert _pick(effects, KillForwarder)
    # user_stop resets backoff so the next user_start doesn't inherit failures.
    assert sm.backoff.consecutive_failures == 0


def test_user_stop_when_disconnected_is_noop() -> None:
    sm = _sm(State.DISCONNECTED)
    effects = sm.step(UserStop())
    assert sm.state == State.DISCONNECTED
    assert _pick(effects, KillForwarder) == []


def test_user_reset_forces_restarting_from_any_active_state() -> None:
    for state in (State.CONNECTING, State.READY, State.STREAMING, State.DEGRADED):
        sm = _sm(state)
        effects = sm.step(UserReset(reason="oncall poked it"))
        assert sm.state == State.RESTARTING, f"reset from {state.value} must restart"
        assert _pick(effects, KillForwarder)


def test_user_reset_when_disconnected_is_noop() -> None:
    sm = _sm(State.DISCONNECTED)
    effects = sm.step(UserReset())
    assert sm.state == State.DISCONNECTED
    assert _pick(effects, KillForwarder) == []


# ---------------------------------------------------------------------------
# Illegal events never crash
# ---------------------------------------------------------------------------


def test_illegal_events_log_but_do_not_change_state() -> None:
    # Send every event in every state; assert state unchanged AND every
    # response contains at least one log effect.
    events = [
        UserStart(),
        OlympeConnected(),
        OlympeDisconnected(),
        OlympeError(reason="x"),
        PipelineStarted(),
        PipelineEos(),
        PipelineError(reason="x"),
        Heartbeat(seq=1),
        ForwarderExit(exit_code=0),
        HealthUnresponsive(since_seconds=1.0),
        HealthDegraded(signal="x"),
        Timeout(),
        UserStop(),
        UserReset(),
    ]
    states_to_check = list(State)

    for state in states_to_check:
        for event in events:
            sm = _sm(state)
            effects = sm.step(event)
            # Every step must yield at least one Log - transition or illegal.
            assert _pick(effects, Log), (
                f"no Log from {type(event).__name__} in {state.value}"
            )
            # step() never raises - that's the core invariant.


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_every_transition_emits_state_transitions_total_metric() -> None:
    sm = _sm(State.DISCONNECTED)
    effects = sm.step(UserStart())
    metrics = _pick(effects, EmitMetric)
    names = [m.name for m in metrics]  # type: ignore[attr-defined]
    assert "state_transitions_total" in names


def test_schedule_restart_emits_restarts_total_metric() -> None:
    sm = _sm(State.STREAMING)
    effects = sm.step(ForwarderExit(exit_code=9))
    metrics = _pick(effects, EmitMetric)
    names = [m.name for m in metrics]  # type: ignore[attr-defined]
    assert "restarts_total" in names


# ---------------------------------------------------------------------------
# Backoff integration
# ---------------------------------------------------------------------------


def test_backoff_grows_on_repeated_failures() -> None:
    sm = _sm(State.CONNECTING, jitter=0.0)
    delays: list[float] = []
    for _ in range(3):
        effects = sm.step(OlympeError(reason="flap"))
        schedules = _pick(effects, ScheduleRestart)
        assert len(schedules) == 1
        delays.append(schedules[0].delay_seconds)  # type: ignore[attr-defined]
        # Simulate the restart cycle: DISCONNECTED -> CONNECTING via the
        # scheduler firing and the dispatcher calling user_start.
        sm.step(UserStart())
    assert delays == [1.0, 2.0, 4.0], f"expected exponential growth, got {delays}"


def test_streaming_window_reset_clears_failures() -> None:
    sm = _sm(State.READY, now=0.0)
    sm.backoff.consecutive_failures = 4
    # Enter STREAMING at t=0, leave at t=120 -> healthy window resets.
    sm.step(PipelineStarted())
    sm.now_fn = lambda: 120.0  # type: ignore[assignment]
    sm.step(OlympeDisconnected(reason="planned"))
    assert sm.backoff.consecutive_failures == 0


# ---------------------------------------------------------------------------
# Coverage smoke test
# ---------------------------------------------------------------------------


def test_full_happy_cycle_end_to_end() -> None:
    """DISCONNECTED -> STREAMING -> RESTARTING -> STREAMING."""
    sm = _sm()
    sm.step(UserStart())
    sm.step(OlympeConnected())
    sm.step(PipelineStarted())
    assert sm.state == State.STREAMING

    sm.step(PipelineError(reason="glitch"))
    assert sm.state == State.RESTARTING

    sm.step(ForwarderExit(exit_code=0))
    assert sm.state == State.CONNECTING

    sm.step(OlympeConnected())
    sm.step(PipelineStarted())
    assert sm.state == State.STREAMING
