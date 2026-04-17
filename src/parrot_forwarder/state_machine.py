"""
Supervisor state machine.

Pure, synchronous, no IO. The supervisor runtime (T07) drives this by
feeding :class:`Event` instances into :meth:`StateMachine.step` and
executing the returned :class:`SideEffect` descriptors. That separation
is what makes the state machine trivially unit-testable - every
transition from ``v2/architecture/state-machine.md`` is exercised with
plain function calls, no subprocess, no asyncio, no clocks.

Design rules this module follows:

  1. Pure. The only state is what the :class:`StateMachine` instance
     holds. No global clocks, no random number generators except one
     explicitly injected for jitter. Tests pass a fixed ``monotonic`` and
     a seeded RNG.
  2. Typed. States are an enum; events are dataclasses; side effects are
     dataclasses. You can grep for ``SideEffect`` subclasses and find
     every behavior the supervisor is expected to perform.
  3. Illegal events do not crash. They produce a :class:`Log` side effect
     and leave the state unchanged.
  4. Backoff lives in :mod:`parrot_forwarder.backoff`. The state machine
     just asks it for the next delay.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from .backoff import BackoffPolicy, BackoffState

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


class State(StrEnum):
    """Supervisor states - mirror exactly ``v2/architecture/state-machine.md``."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    STREAMING = "STREAMING"
    DEGRADED = "DEGRADED"
    RESTARTING = "RESTARTING"


#: Per-state timeout in seconds. ``None`` means "no timeout for this state".
STATE_TIMEOUT_SECONDS: dict[State, float | None] = {
    State.DISCONNECTED: None,
    State.CONNECTING: 30.0,
    State.READY: 10.0,
    State.STREAMING: None,
    State.DEGRADED: 15.0,
    State.RESTARTING: 5.0,
}


# ---------------------------------------------------------------------------
# Events (inputs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """Base class for every event the state machine accepts."""


# -- Forwarder-originated events --------------------------------------------


@dataclass(frozen=True)
class OlympeConnected(Event):
    pass


@dataclass(frozen=True)
class OlympeDisconnected(Event):
    reason: str = ""


@dataclass(frozen=True)
class OlympeError(Event):
    reason: str


@dataclass(frozen=True)
class PipelineStarted(Event):
    pass


@dataclass(frozen=True)
class PipelineEos(Event):
    pass


@dataclass(frozen=True)
class PipelineError(Event):
    reason: str


@dataclass(frozen=True)
class Heartbeat(Event):
    seq: int
    healthy: bool = True


@dataclass(frozen=True)
class ForwarderExit(Event):
    exit_code: int


# -- User / API events ------------------------------------------------------


@dataclass(frozen=True)
class UserStart(Event):
    pass


@dataclass(frozen=True)
class UserStop(Event):
    pass


@dataclass(frozen=True)
class UserReset(Event):
    reason: str = "operator requested"


# -- Internal / health monitor events ---------------------------------------


@dataclass(frozen=True)
class HealthUnresponsive(Event):
    """No heartbeat for longer than the configured timeout."""

    since_seconds: float


@dataclass(frozen=True)
class HealthDegraded(Event):
    """Pipeline is up but a specific signal (FPS, RSSI, battery) is failing."""

    signal: str


@dataclass(frozen=True)
class Timeout(Event):
    """A per-state timeout fired. The dispatcher is expected to synthesize this
    when ``STATE_TIMEOUT_SECONDS[current_state]`` elapses without a transition.
    """


# ---------------------------------------------------------------------------
# Side-effect descriptors (outputs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SideEffect:
    """Base class for all side-effect descriptors.

    The state machine never performs IO. It returns a list of these; the
    dispatcher (T07) is responsible for executing them.
    """


@dataclass(frozen=True)
class SpawnForwarder(SideEffect):
    """Start (or restart) the forwarder subprocess."""


@dataclass(frozen=True)
class KillForwarder(SideEffect):
    """Terminate the forwarder subprocess (SIGTERM, then SIGKILL after grace)."""

    grace_seconds: float = 5.0


@dataclass(frozen=True)
class ScheduleRestart(SideEffect):
    """Arm a timer that will fire ``UserStart`` after ``delay_seconds``."""

    delay_seconds: float
    reason: str


@dataclass(frozen=True)
class SetTimeout(SideEffect):
    """Arm the per-state watchdog timer for the NEW state. ``None`` disables."""

    seconds: float | None


@dataclass(frozen=True)
class EmitMetric(SideEffect):
    """Record a counter/gauge for Prometheus later."""

    name: str
    labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Log(SideEffect):
    """Structured log line emitted for the transition or illegal event."""

    level: str
    message: str
    fields: tuple[tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


@dataclass
class StateMachine:
    """Holder of :class:`State` + backoff bookkeeping.

    Construct one per supervisor run. The dispatcher calls :meth:`step`
    for every incoming event and executes the returned side effects in
    order. State changes and illegal events are *always* logged.
    """

    state: State = State.DISCONNECTED
    backoff: BackoffState = field(default_factory=BackoffState)
    #: Callable returning current monotonic seconds. Injected so tests can
    #: assert streaming-window resets deterministically. Default uses the
    #: system monotonic clock.
    now_fn: Callable[[], float] = field(default_factory=lambda: _default_now)
    #: Monotonic timestamp at which the current STREAMING window began, or
    #: ``None`` if we are not in STREAMING.
    _streaming_since: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(self, event: Event) -> list[SideEffect]:
        """Advance the state machine with ``event`` and return side effects.

        The returned list preserves the order the dispatcher should use:
        first logs / metrics, then lifecycle actions, last the SetTimeout
        for the new state.
        """
        handler = _HANDLERS.get(type(event))
        if handler is None:
            return [self._illegal(event, reason="unknown event type")]
        return handler(self, event)

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    def _transition(
        self,
        new_state: State,
        *,
        reason: str,
        extra: list[SideEffect] | None = None,
    ) -> list[SideEffect]:
        """Move from ``self.state`` to ``new_state``, emitting the canonical
        side-effect sequence: log → metrics → optional extras → SetTimeout.
        """
        from_state = self.state
        effects: list[SideEffect] = [
            Log(
                level="info",
                message=f"state transition {from_state.value} -> {new_state.value}",
                fields=(
                    ("event", "state_transition"),
                    ("from", from_state.value),
                    ("to", new_state.value),
                    ("reason", reason),
                ),
            ),
            EmitMetric(
                name="state_transitions_total",
                labels=(
                    ("from", from_state.value),
                    ("to", new_state.value),
                    ("reason", reason),
                ),
            ),
        ]

        # Update streaming-window bookkeeping BEFORE side effects so backoff
        # sees the right "were we streaming cleanly?" signal.
        if new_state == State.STREAMING and from_state != State.STREAMING:
            self._streaming_since = self.now_fn()
        elif from_state == State.STREAMING and new_state != State.STREAMING:
            # Moving out of STREAMING: reset-if-we-were-healthy check.
            if self._streaming_since is not None:
                self.backoff.record_streaming_window(self.now_fn() - self._streaming_since)
            self._streaming_since = None

        self.state = new_state
        if extra:
            effects.extend(extra)
        effects.append(SetTimeout(STATE_TIMEOUT_SECONDS[new_state]))
        return effects

    def _stay(self, reason: str, extra: list[SideEffect] | None = None) -> list[SideEffect]:
        """Log an event that doesn't change state (e.g. heartbeat)."""
        effects: list[SideEffect] = [
            Log(
                level="debug",
                message=f"staying in {self.state.value}",
                fields=(("event", "state_noop"), ("reason", reason)),
            )
        ]
        if extra:
            effects.extend(extra)
        return effects

    def _illegal(self, event: Event, *, reason: str) -> SideEffect:
        return Log(
            level="warning",
            message=f"illegal event {type(event).__name__} in state {self.state.value}",
            fields=(
                ("event", "illegal_event"),
                ("state", self.state.value),
                ("reason", reason),
                ("event_type", type(event).__name__),
            ),
        )

    def _schedule_restart(self, reason: str) -> list[SideEffect]:
        delay = self.backoff.record_failure()
        return [
            Log(
                level="info",
                message=f"scheduling restart in {delay:.2f}s",
                fields=(
                    ("event", "schedule_restart"),
                    ("reason", reason),
                    ("delay_seconds", f"{delay:.3f}"),
                    ("consecutive_failures", str(self.backoff.consecutive_failures)),
                ),
            ),
            EmitMetric(
                name="restarts_total",
                labels=(("reason", reason),),
            ),
            ScheduleRestart(delay_seconds=delay, reason=reason),
        ]


def _default_now() -> float:
    """Default monotonic clock. Indirected so tests can inject a fake."""
    import time

    return time.monotonic()


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------
#
# Each handler is a pure function (well, it mutates ``sm.state`` via
# ``_transition`` but otherwise has no side effects). The mapping below
# is the canonical truth table from ``state-machine.md#transitions``.


def _on_user_start(sm: StateMachine, _event: UserStart) -> list[SideEffect]:
    if sm.state == State.DISCONNECTED:
        return sm._transition(
            State.CONNECTING,
            reason="user_start",
            extra=[SpawnForwarder()],
        )
    # Idempotent: starting when already started is not an error.
    return sm._stay(reason="user_start_already_running")


def _on_user_stop(sm: StateMachine, _event: UserStop) -> list[SideEffect]:
    if sm.state == State.DISCONNECTED:
        return sm._stay(reason="user_stop_already_disconnected")
    # Terminal stop: no auto-restart. Kill the child and go idle.
    sm.backoff.reset()
    return sm._transition(
        State.DISCONNECTED,
        reason="user_stop",
        extra=[KillForwarder()],
    )


def _on_user_reset(sm: StateMachine, event: UserReset) -> list[SideEffect]:
    # Reset is a forced restart regardless of current state.
    if sm.state == State.DISCONNECTED:
        return sm._stay(reason="user_reset_while_disconnected")
    return sm._transition(
        State.RESTARTING,
        reason=f"user_reset:{event.reason}",
        extra=[KillForwarder()],
    )


def _on_olympe_connected(sm: StateMachine, _event: OlympeConnected) -> list[SideEffect]:
    if sm.state == State.CONNECTING:
        return sm._transition(State.READY, reason="olympe_connected")
    return [sm._illegal(_event, reason=f"olympe_connected in {sm.state.value}")]


def _on_olympe_disconnected(sm: StateMachine, _event: OlympeDisconnected) -> list[SideEffect]:
    # Disconnect in any active state triggers a restart cycle.
    if sm.state in (State.READY, State.STREAMING, State.DEGRADED):
        return sm._transition(
            State.RESTARTING,
            reason="olympe_disconnected",
            extra=[KillForwarder()],
        )
    if sm.state == State.CONNECTING:
        # Connect never completed - schedule a retry.
        extras = [KillForwarder(grace_seconds=0.0), *sm._schedule_restart("olympe_disconnected")]
        return sm._transition(
            State.DISCONNECTED,
            reason="olympe_disconnected_during_connect",
            extra=extras,
        )
    return [sm._illegal(_event, reason=f"olympe_disconnected in {sm.state.value}")]


def _on_olympe_error(sm: StateMachine, event: OlympeError) -> list[SideEffect]:
    if sm.state == State.CONNECTING:
        extras = [KillForwarder(grace_seconds=0.0), *sm._schedule_restart(f"olympe_error:{event.reason}")]
        return sm._transition(
            State.DISCONNECTED,
            reason=f"olympe_error:{event.reason}",
            extra=extras,
        )
    if sm.state in (State.READY, State.STREAMING, State.DEGRADED):
        return sm._transition(
            State.RESTARTING,
            reason=f"olympe_error:{event.reason}",
            extra=[KillForwarder()],
        )
    return [sm._illegal(event, reason=f"olympe_error in {sm.state.value}")]


def _on_pipeline_started(sm: StateMachine, _event: PipelineStarted) -> list[SideEffect]:
    if sm.state == State.READY:
        return sm._transition(State.STREAMING, reason="pipeline_started")
    return [sm._illegal(_event, reason=f"pipeline_started in {sm.state.value}")]


def _on_pipeline_eos(sm: StateMachine, _event: PipelineEos) -> list[SideEffect]:
    if sm.state in (State.READY, State.STREAMING, State.DEGRADED):
        return sm._transition(
            State.RESTARTING,
            reason="pipeline_eos",
            extra=[KillForwarder()],
        )
    return [sm._illegal(_event, reason=f"pipeline_eos in {sm.state.value}")]


def _on_pipeline_error(sm: StateMachine, event: PipelineError) -> list[SideEffect]:
    if sm.state in (State.READY, State.STREAMING, State.DEGRADED):
        return sm._transition(
            State.RESTARTING,
            reason=f"pipeline_error:{event.reason}",
            extra=[KillForwarder()],
        )
    return [sm._illegal(event, reason=f"pipeline_error in {sm.state.value}")]


def _on_heartbeat(sm: StateMachine, event: Heartbeat) -> list[SideEffect]:
    if sm.state == State.DEGRADED and event.healthy:
        # Recovered: pop back to STREAMING.
        return sm._transition(State.STREAMING, reason="heartbeat_healthy")
    if sm.state in (State.STREAMING, State.READY, State.DEGRADED):
        return sm._stay(reason="heartbeat")
    return [sm._illegal(event, reason=f"heartbeat in {sm.state.value}")]


def _on_forwarder_exit(sm: StateMachine, event: ForwarderExit) -> list[SideEffect]:
    if sm.state == State.RESTARTING:
        # Expected: dispatcher will spawn a fresh forwarder after backoff.
        return sm._transition(
            State.CONNECTING,
            reason="restart_complete",
            extra=[SpawnForwarder()],
        )
    if sm.state == State.DISCONNECTED:
        # Expected after user_stop.
        return sm._stay(reason="forwarder_exit_while_disconnected")
    # Unexpected exit from any active state = crash. Restart with backoff.
    reason = f"unexpected_exit:code={event.exit_code}"
    extras = [KillForwarder(grace_seconds=0.0), *sm._schedule_restart(reason)]
    return sm._transition(
        State.DISCONNECTED,
        reason=reason,
        extra=extras,
    )


def _on_health_unresponsive(sm: StateMachine, _event: HealthUnresponsive) -> list[SideEffect]:
    if sm.state == State.STREAMING:
        return sm._transition(State.DEGRADED, reason="health_unresponsive")
    if sm.state == State.DEGRADED:
        # Already degraded - stay, dispatcher's watchdog will timeout us.
        return sm._stay(reason="health_unresponsive_while_degraded")
    return [sm._illegal(_event, reason=f"health_unresponsive in {sm.state.value}")]


def _on_health_degraded(sm: StateMachine, event: HealthDegraded) -> list[SideEffect]:
    if sm.state == State.STREAMING:
        return sm._transition(
            State.DEGRADED,
            reason=f"health_degraded:{event.signal}",
        )
    if sm.state == State.DEGRADED:
        return sm._stay(reason=f"health_degraded_while_degraded:{event.signal}")
    return [sm._illegal(event, reason=f"health_degraded in {sm.state.value}")]


def _on_timeout(sm: StateMachine, _event: Timeout) -> list[SideEffect]:
    # Per-state timeout interpretation per state-machine.md.
    if sm.state == State.CONNECTING:
        extras = [KillForwarder(grace_seconds=0.0), *sm._schedule_restart("connecting_timeout")]
        return sm._transition(
            State.DISCONNECTED,
            reason="connecting_timeout",
            extra=extras,
        )
    if sm.state == State.READY:
        return sm._transition(
            State.RESTARTING,
            reason="ready_timeout",
            extra=[KillForwarder()],
        )
    if sm.state == State.DEGRADED:
        return sm._transition(
            State.RESTARTING,
            reason="degraded_timeout",
            extra=[KillForwarder()],
        )
    if sm.state == State.RESTARTING:
        # Forwarder didn't exit after the grace SIGTERM; escalate.
        return sm._stay(
            reason="restarting_grace_expired",
            extra=[KillForwarder(grace_seconds=0.0)],
        )
    # DISCONNECTED and STREAMING have no timeout; a fired Timeout here is a
    # dispatcher bug but we don't crash.
    return [sm._illegal(_event, reason=f"timeout in {sm.state.value}")]


_HANDLERS: dict[type[Event], Callable[..., list[SideEffect]]] = {
    UserStart: _on_user_start,
    UserStop: _on_user_stop,
    UserReset: _on_user_reset,
    OlympeConnected: _on_olympe_connected,
    OlympeDisconnected: _on_olympe_disconnected,
    OlympeError: _on_olympe_error,
    PipelineStarted: _on_pipeline_started,
    PipelineEos: _on_pipeline_eos,
    PipelineError: _on_pipeline_error,
    Heartbeat: _on_heartbeat,
    ForwarderExit: _on_forwarder_exit,
    HealthUnresponsive: _on_health_unresponsive,
    HealthDegraded: _on_health_degraded,
    Timeout: _on_timeout,
}


# ---------------------------------------------------------------------------
# Factory that wires in a sane backoff policy
# ---------------------------------------------------------------------------


def make_state_machine(
    policy: BackoffPolicy | None = None,
    now_fn: Callable[[], float] | None = None,
) -> StateMachine:
    """Build a :class:`StateMachine` with a fresh backoff state."""
    return StateMachine(
        backoff=BackoffState(policy=policy or BackoffPolicy()),
        now_fn=now_fn or _default_now,
    )
