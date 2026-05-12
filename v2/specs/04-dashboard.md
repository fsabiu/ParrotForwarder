# Spec: Dashboard

Single-page app served by the supervisor at `/`. Localhost-only.

## Layout (single screen, no navigation)

```
+----------------------------------------------------+
| ParrotForwarder          [ STREAMING ]  uptime 12m |   <- header: state badge + uptime
+----------------------------------------------------+
|                         |                          |
|   [ live video preview] | Battery:   78%           |
|                         | GPS:       11 sat, fixed |
|                         | RSSI:      -52 dBm       |
|                         | FPS:       29.94         |
|                         | Bitrate:   3120 kbps     |
|                         | Restarts:  2             |
|                         +--------------------------+
|                         | Altitude (MSL): 124.3 m  |
|                         | Speed:    1.2 / 0.0 m/s  |
|                         | Yaw:      87 deg         |
|                         +--------------------------+
|                         | [ Start ][ Stop ][ Reset]|
+----------------------------------------------------+
|  Event log (tail)                                  |
|  14:23:14  state STREAMING                         |
|  14:23:11  state READY -> STREAMING                |
|  14:23:09  olympe connected                        |
+----------------------------------------------------+
```

## Interactions

- State badge color: green (STREAMING), yellow (READY / DEGRADED / CONNECTING), red (DISCONNECTED / RESTARTING), grey (unknown).
- Telemetry values update at the configured telemetry rate from `/stream/telemetry`
  (30 Hz by default). Operators can change the target telemetry Hz from the
  dashboard; active workers are reset so the next worker starts with the new
  KLV/WebSocket cadence.
- Event log tails `/stream/events`, newest at top, cap at 200 rows.
- Buttons call `/control/start|stop|reset`. Disabled when action is invalid in current state.
- Reset button confirms with a native `window.confirm`. No other modals.

## Non-goals

- Theme switcher, multi-drone, maps, charts. Ship one screen that works.
- Mobile-responsive is nice-to-have, not blocking.

## Tech

Decided in [ADR-003](../decisions/ADR-003-frontend-stack.md). Lean baseline: vanilla TS or Svelte. No React unless ADR says so - React brings a toolchain heavier than the feature set warrants.

## Build and serve

- Built assets in `dashboard/dist/`, committed to branch so supervisor doesn't need node at runtime.
- Dev workflow: `npm run dev` runs Vite; supervisor serves dist in production.
- Hashed filenames for cache busting; `index.html` is `no-cache`.

## Tests

- Playwright smoke: open `/`, confirm state badge renders, telemetry updates, Reset triggers a REST POST.
- No unit tests for trivial components. Focus effort on integration.
