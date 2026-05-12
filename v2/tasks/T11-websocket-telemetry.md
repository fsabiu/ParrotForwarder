# T11 - WebSocket events and telemetry

**Phase**: 2
**Depends on**: T10
**Estimated effort**: M

## Goal

Real-time streams for state events and telemetry, both WebSocket.

## Acceptance criteria

- `/stream/events` emits state transitions, logs (warning+), and restart notifications.
- `/stream/telemetry` emits decoded telemetry at `?rate=<hz>` (default 30, max = configured drone rate).
- Per-client rate limiting; slow consumers get backpressure, then disconnect.
- Graceful close on supervisor shutdown.

## Files touched

- `src/parrot_forwarder/supervisor/api/stream.py`
- `tests/test_stream.py`

## How to verify

```bash
websocat ws://localhost:8080/stream/events
websocat 'ws://localhost:8080/stream/telemetry?rate=2'
```

## Notes

- Keep the broadcast model simple: one publisher per stream, fan-out via asyncio queues per subscriber.
- Telemetry frames come from the forwarder over IPC; supervisor samples/rate-limits before fan-out.
