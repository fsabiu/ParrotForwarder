# ParrotForwarder v2 - Developer Guide

## Layout

```
src/parrot_forwarder/
  config.py           pydantic v2 Config + layered loader
  backoff.py          BackoffPolicy, BackoffState, compute_delay
  state_machine.py    State enum, Event dataclasses, SideEffect descriptors,
                      StateMachine.step(event) -> list[SideEffect]
  ipc.py              Discriminated-union IPC schemas + encode/decode
  metrics.py          prometheus_client-backed Metrics
  logging_setup.py    JsonFormatter + configure_logging(LoggingConfig)
  supervisor/
    __init__.py       asyncio Supervisor owning the worker subprocess
    health.py         HealthMonitor + thresholds
    api/
      __init__.py     FastAPI app factory
      stream.py       /stream/events + /stream/telemetry
  forwarder/
    worker.py         subprocess entry point (parrot-forwarder-worker)
  dashboard/
    static/           vanilla HTML/JS/CSS bundle
  testing/
    mock_drone.py     MockDrone + mock_drone_factory for tests
```

## Architecture tour

1. **Config (T02)** - pydantic models with `extra="forbid"`. Layered loader
   merges defaults < yaml < env < cli; never reads files at import time.
2. **State machine (T06)** - pure. `step(event)` returns a list of
   `SideEffect` descriptors. No IO, no clocks (inject `now_fn` for
   streaming-window reset).
3. **Supervisor (T07)** - asyncio runtime. Translates worker IPC frames
   into state-machine events via `ipc_to_event`, executes returned
   side effects (`SpawnForwarder`, `KillForwarder`, `ScheduleRestart`,
   `SetTimeout`, `EmitMetric`, `Log`).
4. **Health monitor (T08)** - stateful observer over heartbeats and
   pipeline metrics. Emits `HealthUnresponsive` / `HealthDegraded`
   events the supervisor forwards to the state machine.
5. **HTTP surface (T10-T12)** - FastAPI app with REST, WebSocket
   streams, and Prometheus metrics. All mounted on the same app.

## How to add a new state-machine event

1. Add a frozen dataclass to `state_machine.py` inheriting `Event`.
2. Register a handler in `_HANDLERS` and implement the transition.
3. Add unit tests to `tests/test_state_machine.py` covering the event in
   every state (happy path, illegal paths).
4. If the event originates from the worker, add an IPC message to
   `ipc.py` and map it in `_IPC_TO_EVENT` in `supervisor/__init__.py`.

## How to add a new metric

1. Add the gauge/counter/histogram to `Metrics.__init__` in `metrics.py`
   under the `parrot_forwarder_` prefix with a HELP string.
2. Expose a recorder method (e.g. `record_something`) so the supervisor
   dispatcher is the only place that touches the metric internals.
3. Add an expectation to `tests/test_metrics.py` that the new metric is
   exposed via `/metrics` with the right name and shape.

## Tests

```bash
make test        # pytest -m "not live and not slow"
make lint        # ruff check .
make typecheck   # mypy src/parrot_forwarder
make ci          # everything the GitHub Actions workflow runs
```

See [v2/specs/05-testing.md](../v2/specs/05-testing.md) for the full testing
strategy. Live-drone tests are marked `@pytest.mark.live` and only run on a
host with a connected Parrot Anafi.

## Release

- Bump `[project].version` in `pyproject.toml` and `__version__` in
  `src/parrot_forwarder/__init__.py` (keep them in sync).
- Update `CHANGELOG.md` (when we add one) with the user-visible deltas.
- Tag: `git tag v2.0.0 && git push --tags`.
- GitHub release notes are generated from the CHANGELOG; they must
  point at the v2/ folder for design context.
