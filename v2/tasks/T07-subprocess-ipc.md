# T07 - Forwarder subprocess and IPC

**Phase**: 1
**Depends on**: T06, T03
**Estimated effort**: L

## Goal

Stand up the supervisor -> forwarder subprocess topology over a Unix domain socket. Wire the state machine to real subprocess lifecycle events.

## Acceptance criteria

- `src/parrot_forwarder/supervisor/__init__.py` holds the asyncio `Supervisor` class.
- `src/parrot_forwarder/supervisor/ipc.py` implements the UDS server: newline-delimited JSON, schema-validated, back-pressure aware (drop telemetry before events).
- `src/parrot_forwarder/forwarder/worker.py` is the subprocess entry point (installed as console script `parrot-forwarder-worker`), which connects to the UDS, runs the v1 `ParrotForwarder` logic, and emits IPC events.
- Supervisor spawns the worker using `asyncio.create_subprocess_exec` and supervises it. On crash: log, run state machine, respawn with backoff.
- Graceful shutdown: SIGTERM supervisor -> supervisor sends `stop` over IPC -> worker exits cleanly; 3 s grace then SIGKILL.
- No zombies. Verified by PID accounting in integration test.

## Files touched

- `src/parrot_forwarder/supervisor/` (new subpackage)
- `src/parrot_forwarder/forwarder/worker.py` (wraps v1 main.py)
- `src/parrot_forwarder/ipc.py` (shared schemas)
- `tests/test_ipc.py` and `tests/test_supervisor_integration.py`

## How to verify

```bash
pytest tests/test_supervisor_integration.py -v
# also: run supervisor manually against mock drone, Ctrl-C, verify no leftover processes
```

## Notes

- Prefer `SO_PEERCRED` / fs permissions over shared secrets.
- IPC message schema lives in `ipc.py` so supervisor and worker import the same models.
