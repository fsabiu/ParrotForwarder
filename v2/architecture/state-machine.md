# Supervisor State Machine

## States

| State | Meaning | Timeout | On timeout |
|---|---|---|---|
| `DISCONNECTED` | No forwarder running. Initial state. | none | - |
| `CONNECTING` | Forwarder subprocess spawned; Olympe trying to reach drone. | 30 s | -> `DISCONNECTED`, schedule restart with backoff |
| `READY` | Olympe connected; telemetry/control live, video not yet available. | none | - |
| `STREAMING` | Pipeline active, heartbeats healthy. | none | - |
| `DEGRADED` | Pipeline active but one or more health signals failing. | 15 s | -> `RESTARTING` |
| `RESTARTING` | Terminating forwarder, about to re-spawn. | 5 s (graceful), then SIGKILL | -> `CONNECTING` |

## Events (inputs)

From the forwarder (over IPC):

- `olympe.connected` - drone reachable, arsdk ready
- `olympe.disconnected` - connection lost
- `olympe.error(reason)` - fatal olympe error
- `pipeline.started` - GStreamer pipeline playing
- `pipeline.eos` - end-of-stream (source gone)
- `pipeline.error(reason)` - pipeline fault; `reason=video_unavailable` means control stayed up but RTSP is not live
- `heartbeat(seq, metrics)` - every 1 s
- `exit(code)` - child died

From the API (user actions):

- `user.start`
- `user.stop`
- `user.reset` (forces RESTARTING regardless of current state)

From the health monitor (internal):

- `health.unresponsive` - no heartbeat for 5 s
- `health.degraded(signal)` - e.g. FPS dropped to 0, RSSI collapsed, battery critical

## Transitions

```
DISCONNECTED + user.start           -> CONNECTING
CONNECTING   + olympe.connected     -> READY
CONNECTING   + olympe.error         -> DISCONNECTED (backoff)
CONNECTING   + timeout              -> DISCONNECTED (backoff)
READY        + pipeline.started     -> STREAMING
READY        + pipeline.error(video_unavailable) -> READY
READY        + pipeline.error(other) -> RESTARTING
STREAMING    + olympe.disconnected  -> RESTARTING
STREAMING    + pipeline.error(video_unavailable) -> READY
STREAMING    + pipeline.error(other) -> RESTARTING
STREAMING    + pipeline.eos         -> RESTARTING
STREAMING    + health.unresponsive  -> DEGRADED
STREAMING    + health.degraded      -> DEGRADED
DEGRADED     + heartbeat (healthy)  -> STREAMING
DEGRADED     + timeout              -> RESTARTING
*            + user.reset           -> RESTARTING
*            + user.stop            -> DISCONNECTED (no auto-restart)
RESTARTING   + exit                 -> CONNECTING (after backoff)
```

Any state + `exit(code != 0)` also goes to `RESTARTING` (with `RESTARTING` as a no-op).

## Backoff policy

Restart delay = `min(max_delay, base_delay * 2^(consecutive_failures - 1)) + jitter`

- `base_delay` = 1 s
- `max_delay` = 60 s
- `jitter` = uniform random in `[0, 1)` seconds
- `consecutive_failures` resets to 0 after 60 s of continuous `STREAMING`.

Rationale: aggressive first retry (drones often just power-cycle), but no tight loop against a sustained fault (bad cable, dead battery). `READY` intentionally has no timeout so the operator can see truthful "controller up / video absent" behavior without a restart storm.

## Metrics exported

- `state{name}` - gauge, 1 for current state, 0 for others
- `state_transitions_total{from,to,reason}` - counter
- `state_duration_seconds{name}` - histogram of dwell time per state
- `restarts_total{reason}` - counter (reason = pipeline-error, olympe-disconnected, etc.)
- `heartbeat_lag_seconds` - gauge, seconds since last heartbeat

## Notes for implementation

- Transitions must be logged as a single structured log line with `event`, `from`, `to`, `reason`.
- The state machine object should be pure: takes event, returns new state + side effects (as a list of descriptors the dispatcher then executes). This makes it unit-testable without any real subprocess.
- Do not add implicit transitions from user actions while in `RESTARTING`; queue them and replay after the next state change. Otherwise a fast reset click can interleave with the respawn.
