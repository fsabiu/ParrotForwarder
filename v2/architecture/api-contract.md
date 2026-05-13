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
The `field` object carries advertised dashboard/SRT/Tailscale endpoint metadata
for operators and detector handoff checks; it does not change listen/bind
behavior.

### `PUT /config/forwarder/telemetry-fps`

Update the in-memory telemetry/KLV target rate. Valid range: 1-100 Hz. If the
worker is active, the supervisor requests a controlled reset so the next worker
starts with the new telemetry cadence. Persist the value in `config.yaml` or env
for reboot durability.

```
{ "telemetry_fps": 30 }
```

Response:

```
{
  "telemetry_fps": 30,
  "previous_telemetry_fps": 30,
  "restart_requested": true,
  "state": "STREAMING",
  "message": "telemetry_fps updated; worker reset requested"
}
```

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

Server-to-client telemetry stream at the configured telemetry rate, 30 Hz by
default. JSON per tick. The payload keeps the top-level summary metrics the
dashboard needs immediately, plus grouped telemetry sections and the raw flat
snapshot for debugging/downstream consumers. The raw snapshot also carries
`olympe_state` and `olympe_event_state` when the real Olympe runtime can supply
the SDK state cache or sticky event payloads.

```
{
  "t": "2026-04-17T14:25:03.101Z",
  "payload": {
    "timestamp": "2026-04-17T14:25:03.101Z",
    "sequence": 140,
    "battery_percent": 77,
    "gps_fix": false,
    "position_valid": false,
    "rssi_dbm": -58,
    "position": {
      "valid": false,
      "source": "default",
      "message": "gps_fix_unavailable",
      "is_default": true,
      "satellites": 0,
      "altitude_msl_m": 124.3,
      "altitude_agl_m": 18.5,
      "ground_altitude_msl_m": 105.8,
      "klv": {
        "latitude": 36.71549,
        "longitude": -4.28795,
        "altitude_msl_m": 10.0
      },
      "raw": {
        "gps_location": { "latitude": 500.0, "longitude": 500.0, "altitude_msl_m": 124.3 }
      }
    },
    "attitude": { "roll_deg": -1.2, "pitch_deg": 3.4, "yaw_deg": 87.1, "heading_deg": 87.1 },
    "gimbal": {
      "absolute_deg": { "yaw": 0.0, "pitch": -45.0, "roll": 0.0 },
      "relative_deg": { "yaw": 0.0, "pitch": -45.0, "roll": 0.0 },
      "offset_deg": { "yaw": 0.0, "pitch": 0.0, "roll": 0.0 }
    },
    "camera": {
      "sensor_width_mm": 6.3,
      "sensor_height_mm": 4.7,
      "focal_length_mm": 23.0,
      "zoom_level": 1.0,
      "h_fov_deg": 76.6,
      "v_fov_deg": 59.3
    },
    "signal": { "rssi_dbm": -58, "link_quality_level": 5, "probable_4g_interference": false },
    "flight": { "state": "hovering", "return_home": { "state": "available", "reason": "finished" } },
    "storage": { "free_space_mb": 1820, "recording_time_remaining_min": 48, "photo_remaining": 350 },
    "system": { "product_name": "Anafi", "software_version": "1.8.2" },
    "raw": { "...": "full flat snapshot omitted here" }
  }
}
```

Rate is configurable by query: `?rate=2` for 2 Hz. A client cannot receive
faster than the worker-published telemetry cadence.

## Static

### `GET /`

Dashboard SPA. Until the assets are fingerprinted, `index.html`, `app.js`, and `style.css` are all served with `Cache-Control: no-cache` so operators do not get a stale UI after a hotfix deployment.

### `GET /preview/stream.m3u8` and `GET /preview/segment-*.ts`

HLS preview. Served by the supervisor from a shared-memory directory the GStreamer pipeline writes to. 2-second segments, 3-segment playlist, live.

## OpenAPI

Generated from FastAPI's schema and committed to `docs/openapi.yaml` as part of Phase 2. The generated file is the source of truth for clients - don't edit by hand.
