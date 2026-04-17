# Spec: Supervisor

## Responsibilities

1. Own the process lifecycle of the forwarder subprocess.
2. Own the state machine and decide when to restart.
3. Expose the HTTP/WS surface.
4. Emit structured logs and metrics.

## Out of scope

- Olympe connection details (live in forwarder).
- GStreamer pipeline (lives in forwarder).
- KLV encoding (untouched from v1).

## Inputs

- Config (see [02-config.md](02-config.md)).
- IPC events from forwarder (see [../architecture/overview.md](../architecture/overview.md)).
- HTTP/WS requests from dashboard or curl.

## Outputs

- HTTP/WS responses.
- Prometheus metrics.
- Rotating JSON log files.
- Signals to forwarder subprocess (SIGTERM for graceful stop, SIGKILL after grace period).

## Behaviour

- On start: load config, bind HTTP server on loopback, transition `DISCONNECTED -> CONNECTING` if `auto_start: true` in config; otherwise wait for `POST /control/start`.
- On SIGTERM: reject new API writes, gracefully stop forwarder, flush logs, exit 0.
- On SIGHUP: reload config (only config fields marked `reloadable: true` in the schema).
- If the forwarder subprocess exits without IPC notice within the last 2 s, assume crash, log with full exit info, apply backoff, respawn.
- If the IPC socket is dropped but the child is still alive, kill the child; do not attempt to reattach (state is already inconsistent).
- Never block the asyncio loop on a subprocess join; always use `asyncio.wait_for`.

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Forwarder crashes | SIGCHLD + exit code | Respawn with backoff |
| Forwarder hangs (no heartbeat 5 s) | Health monitor timer | SIGTERM, wait 3 s, SIGKILL, respawn |
| Olympe reports disconnected | IPC event | Transition to RESTARTING |
| Pipeline EOS | IPC event | Transition to RESTARTING |
| Config reload fails | Exception during reload | Keep old config, log error, respond 500 on future `/config` reload |
| IPC socket dies | Socket error | Kill child, respawn |

## Non-functional requirements

- Memory: supervisor steady state under 100 MB RSS.
- CPU: supervisor idle under 2% on an ARM64 core.
- Startup to `DISCONNECTED` ready to accept API: under 1 s.
- Restart loop latency (end of STREAMING -> next STREAMING): under 15 s when the drone is healthy.

## Tests required

- State machine unit tests: every listed transition, including timeouts.
- IPC protocol: round-trip all event types with a loopback socket.
- Subprocess lifecycle: spawn/kill/respawn, verify PIDs change and no zombies.
- Config reload: valid reload, invalid reload, partial reload of non-reloadable field.
- Graceful shutdown: SIGTERM during each state, verify no leaked processes.
- Backoff: simulate 5 consecutive failures, assert delays.
