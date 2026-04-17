# ADR-001 - Supervisor architecture

**Status**: proposed
**Date**: 2026-04-17

## Context

v1 runs as a single process with two threads. If Olympe or GStreamer crashes the interpreter, systemd restarts the whole thing. That's acceptable as a last resort but gives zero operator visibility, zero structured restart reason, and drops WebSocket/HTTP connections to any dashboard we attach.

Three shapes are plausible for v2:

1. **Threads (v1+)** - add a watchdog thread in the same process. Keep it simple.
2. **Subprocess** - supervisor process forks/spawns a forwarder subprocess; IPC over UDS.
3. **Systemd template + socket activation** - let systemd be the supervisor, use `BindsTo=` and `Restart=on-failure`; have the "supervisor" be purely HTTP/dashboard fronted by unit files.

## Decision

Go with option 2, subprocess + UDS IPC.

## Consequences

Easier:
- Crash isolation. A segfault in Olympe's C extension or a GStreamer bus error can't kill the supervisor or drop the dashboard's WebSocket.
- Explicit restart reason. The supervisor sees exit codes, IPC last-frame, and heartbeat lag; it composes a structured reason code.
- Unit testing. Supervisor and state machine are plain async Python with no real GStreamer deps.

Harder:
- More moving parts. Two processes, one socket. Startup latency a bit higher.
- Protocol versioning. The IPC message schema becomes a real interface; forwarder and supervisor must stay in sync on upgrades.
- Zombie reaping. We accept the cost and verify in tests.

Obligations:
- Own the IPC protocol schema (pydantic models in `ipc.py`).
- Signal handling hygiene (supervisor owns SIGINT/SIGTERM; forwarder ignores and exits on IPC command).
- PID / zombie discipline in integration tests.

## Alternatives considered

- **Threads**. Too entangled with v1's failure modes. A C-level crash still brings down the supervisor and the dashboard. Rejected.
- **Systemd template**. Moves the problem into systemd units. Dashboard + state machine still need to live somewhere; they end up as a third service that talks to the forwarder via DBus or files, which is worse than UDS. Rejected.
