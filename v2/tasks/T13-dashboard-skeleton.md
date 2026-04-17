# T13 - Dashboard SPA skeleton

**Phase**: 3
**Depends on**: T10, T11
**Estimated effort**: M

## Goal

Serve a minimal dashboard that shows state + telemetry. No video yet (T14), no controls yet (T15).

## Acceptance criteria

- `dashboard/` Vite project with the stack chosen in [ADR-003](../decisions/ADR-003-frontend-stack.md).
- Built assets land in `dashboard/dist/`, committed to the v2 branch.
- Supervisor serves `dashboard/dist/` at `/` with correct cache headers.
- Opening `http://localhost:8080/` shows header (name, state badge, uptime) and right column (battery, GPS, RSSI, FPS, bitrate, restart count) wired to `/status` polling + `/stream/telemetry` WS.
- No runtime errors in browser console against a healthy supervisor.

## Files touched

- `dashboard/` (new)
- `src/parrot_forwarder/supervisor/api/static.py` (serves dist)
- `tests/test_dashboard_static.py`

## How to verify

```bash
cd dashboard && npm ci && npm run build
cd .. && parrot-forwarder &
open http://localhost:8080
```
