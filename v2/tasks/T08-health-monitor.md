# T08 - Health monitor

**Phase**: 1
**Depends on**: T07
**Estimated effort**: M

## Goal

Detect unhealthy-but-not-crashed conditions: no heartbeat, FPS collapsed, RSSI dropped, pipeline stalled. Feed these into the state machine as `health.*` events.

## Acceptance criteria

- `src/parrot_forwarder/supervisor/health.py` runs as an asyncio task.
- Tracks heartbeat seq + timestamp; emits `health.unresponsive` after `heartbeat.timeout_seconds`.
- Parses heartbeat metrics (FPS, bitrate, battery); emits `health.degraded(signal=...)` when any crosses a threshold (FPS < 10 for 5 s, battery < 10%, RSSI < -85 dBm).
- Thresholds configurable via `config.yaml`.
- Recovery: once all signals healthy for 5 s, emits `health.recovered`.

## Files touched

- `src/parrot_forwarder/supervisor/health.py`
- `tests/test_health.py`

## How to verify

Unit tests drive the monitor with canned heartbeats via a fake clock.

## Notes

- Use `asyncio.get_event_loop().time()` for monotonic time; parameterize the clock for tests.
