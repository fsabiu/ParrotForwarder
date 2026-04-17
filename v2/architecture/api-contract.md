# API Contract

Supervisor HTTP surface, bound to `127.0.0.1` only.

Base URL: `http://localhost:8080` (configurable). No auth in v2.

Content type: `application/json` unless noted. Errors: RFC 7807 `application/problem+json`.

## REST

### `GET /health`

Liveness. Returns 200 as long as supervisor event loop is alive.

```
{ "status": "ok" }
```

### `GET /status`

Full current state snapshot.

```
{
  "state": "STREAMING",
  "since": "2026-04-17T14:23:11.042Z",
  "uptime_seconds": 812.3,
  "restarts_total": 2,
  "consecutive_failures": 0,
  "drone": {
    "ip": "192.168.53.1",
    "model": "Anafi",
    "battery_percent": 78,
    "gps_fix": true,
    "satellites": 11,
    "rssi_dbm": -52
  },
  "pipeline": {
    "srt_port": 8890,
    "klv_port": 12345,
    "preview_url": "/preview/stream.m3u8",
    "fps": 29.94,
    "bitrate_kbps": 3120
  },
  "last_event": {
    "kind": "pipeline.started",
    "at": "2026-04-17T14:23:12.891Z"
  }
}
```

### `GET /config`

Effective config after layering (defaults < yaml < env < cli), with secrets redacted. Useful for debugging.

### `POST /control/start`

Start forwarding. No body. Idempotent; returns 409 if already past `DISCONNECTED`.

### `POST /control/stop`

Stop forwarding. Moves to `DISCONNECTED` and does not auto-restart until `/control/start` is called.

### `POST /control/reset`

Force a restart regardless of current state. Body optional:

```
{ "reason": "operator requested" }
```

### `GET /metrics`

Prometheus text exposition. See [state-machine.md](state-machine.md) for the metric set.

## WebSocket

### `ws://localhost:8080/stream/events`

Server-to-client stream of state machine events. One JSON object per message.

```
{ "type": "state", "from": "STREAMING", "to": "DEGRADED", "reason": "heartbeat_lag", "at": "..." }
{ "type": "log",   "level": "warning", "message": "...", "at": "..." }
{ "type": "restart", "count": 3, "reason": "pipeline-error", "at": "..." }
```

Client sends nothing. Connection drops when supervisor exits.

### `ws://localhost:8080/stream/telemetry`

Server-to-client telemetry stream at supervisor-rate-limited 10 Hz. JSON per tick, shape matches the KLV fields but as decoded primitives (easier for dashboards than raw KLV).

```
{
  "t": "2026-04-17T14:25:03.101Z",
  "gps": { "lat": 45.4642, "lon": 9.1900, "alt_msl_m": 124.3 },
  "attitude": { "roll_deg": -1.2, "pitch_deg": 3.4, "yaw_deg": 87.1 },
  "gimbal": { "yaw_deg": 0.0, "pitch_deg": -45.0, "roll_deg": 0.0 },
  "camera": { "w": 1280, "h": 720, "focal_mm": 4.0 },
  "battery_percent": 77,
  "speed_mps": { "x": 1.2, "y": 0.0, "z": -0.1 }
}
```

Rate is configurable by query: `?rate=2` for 2 Hz, capped at drone's native update rate.

## Static

### `GET /`

Dashboard SPA. Caches aggressively (`Cache-Control: max-age=86400`) for hashed assets, `no-cache` for `index.html`.

### `GET /preview/stream.m3u8` and `GET /preview/segment-*.ts`

HLS preview. Served by the supervisor from a shared-memory directory the GStreamer pipeline writes to. 2-second segments, 3-segment playlist, live.

## OpenAPI

Generated from FastAPI's schema and committed to `docs/openapi.yaml` as part of Phase 2. The generated file is the source of truth for clients - don't edit by hand.
