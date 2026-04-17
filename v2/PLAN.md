# ParrotForwarder v2 - Plan

## Goals

1. **Autonomous operation** - no manual restarts. The service self-heals when the drone disconnects, USB glitches, the Olympe SDK wedges, or the GStreamer pipeline crashes.
2. **Local dashboard** - a web UI served on `http://localhost:<port>` that shows drone connection state, telemetry, live video preview, and offers start/stop/reset controls.
3. **Programmatic control** - REST endpoints for start/stop/status/reset and a WebSocket stream for live telemetry and events, so the dashboard and future integrations use the same contract.
4. **Observability** - structured JSON logs with rotation, Prometheus-style metrics, and enough session history to diagnose a 1 am outage without an SSH session.
5. **Testability without a drone** - mock Olympe backend, fake GStreamer pipeline, and an in-process SRT receiver fixture so unit and integration tests run in CI without hardware.
6. **Reproducible install** - one command (`make install` / `./scripts/install.sh`) or one compose command (`docker compose up -d --build`) brings a fresh Ubuntu 24.04 ARM64 host from empty to running service; no copy-paste from README.
7. **Truthful, complete telemetry** - publish every practically extractable Olympe field needed by the current geolocation/COP pipeline: raw GPS validity + accuracies, home/RTH state, absolute and relative gimbal attitude, gimbal and camera offsets, zoom/FOV/focal data, link quality, storage, product/version, and motor-flight stats.

## Non-goals (v2)

- Multi-drone support. One drone per process stays the model.
- Cloud streaming endpoints. SRT out stays localhost/LAN; cloud is v3.
- Replacing the v1 KLV encoder. It works; wrap it, don't rewrite it.
- Authentication on the dashboard. Default bare-metal binding stays loopback-only; trusted LAN/VPN exposure via explicit `0.0.0.0` config or Docker compose is allowed for site deployments.
- Replacing GStreamer. The pipeline shape stays; we wrap it with health monitoring.

## Constraints

- **Python 3.11** - Olympe SDK requires this. Stays pinned via pyenv.
- **protobuf==3.20.3** - Olympe's transitive `protobuf==3.7.1` must be force-reinstalled to 3.20.3 (see v1 SETUP_NOTES).
- **System GStreamer** - do not mix with Conda's gstreamer. Install via apt.
- **Parrot Anafi + Skycontroller 3** is the only hardware target. Connection is USB tether, drone reachable at `192.168.53.1`.
- **Ubuntu 24.04 LTS ARM64** is the new target OS (v1 was on 25.04 non-LTS). LTS gives us 5 years and deadsnakes python3.11 support.
- **No breaking changes to the SRT output** - the video pipeline and muxed KLV stay wire-compatible with v1 consumers (detection pipeline).

## Telemetry Scope

- **Truth before convenience** - the dashboard/API must expose whether GPS coordinates are actually valid. Legacy KLV fields may still carry explicit fallback coordinates for downstream compatibility, but the API payload must say when those defaults are being used.
- **Platform altitude semantics stay separate** - publish MSL altitude from GPS, altitude above ground from `AltitudeAboveGroundChanged`, and altitude relative to takeoff from `AltitudeChanged`. Derive `ground_altitude_msl = platform_altitude_msl - altitude_agl` when both inputs exist.
- **Camera/gimbal completeness** - publish absolute and relative gimbal angles, gimbal offset bounds/current values, camera alignment offsets, zoom level, focal length, sensor size, and FOV so downstream geolocation can use the best available orientation model.
- **Signal and health completeness** - publish RSSI, decoded link-quality bits, battery, wind/vibration/heading-lock warnings, recording/storage state, product/version, and motor-flight counters.
- **DEM stays downstream** - the forwarder publishes directly observed telemetry plus simple platform-derived values. Terrain-corrected target projection and DEM preload remain responsibilities of the detection/geolocation pipeline, not ParrotForwarder.

## v1 -> v2 delta (what actually changes)

| Area | v1 | v2 |
|---|---|---|
| Entry point | `ParrotForwarder.py` CLI script | `parrot-forwarder` console script; daemon + CLI subcommands (`run`, `status`, `reset`) |
| Process model | Single process, two threads (telemetry + video) | Supervisor process + forwarder subprocess; supervisor survives forwarder crashes |
| Reconnection | Checks `BatteryStateChanged` every N seconds | State machine with explicit transitions (disconnected -> connecting -> ready -> streaming -> degraded -> restarting), exponential backoff, per-state timeouts, and health across Olympe AND GStreamer |
| Config | 9 CLI flags | `config.yaml` (default `/etc/parrot-forwarder/config.yaml`), CLI flags override |
| Logs | Plain text to stdout / journald | Structured JSON to file (rotating) + stdout; log level per module |
| Control | SIGTERM only | REST API: `POST /control/start`, `/control/stop`, `/control/reset`; WebSocket `/stream/events` |
| Telemetry access | None outside SRT | WebSocket `/stream/telemetry` at configurable rate with grouped payload + raw snapshot |
| Video preview | None (need external SRT client) | HLS/WebRTC preview in dashboard, fed from same pipeline (tee branch) |
| Metrics | None | Prometheus `/metrics` endpoint (FPS, bitrate, uptime, reconnects, drone RSSI, battery %) |
| Tests | 7 scripts all requiring live drone | pytest suite with mock drone; `--live` marker for hardware tests |
| Install | Manual, 6 shell blocks in README | `./scripts/install.sh` - idempotent, handles pyenv + apt + venv + pip |
| Packaging | Raw source + systemd unit | Python wheel + Dockerfile + docker-compose + updated systemd unit with dashboard port |

## Architecture summary

Two processes, one socket between them, one HTTP surface outward:

```
  +---------------------------------------------+
  |  Supervisor (asyncio, FastAPI+uvicorn)       |
  |   - state machine                           |
  |   - REST API   /control/*   /health         |
  |   - WebSocket  /stream/events /telemetry    |
  |   - Static     /    (dashboard SPA)         |
  |   - Prometheus /metrics                     |
  |   - Structured logging, rotating files      |
  +---------------------------------------------+
                 |
                 | Unix domain socket (JSON frames)
                 | + SIGTERM / SIGKILL for restart
                 v
  +---------------------------------------------+
  |  Forwarder subprocess (Python 3.11)          |
  |   - Olympe drone connect                    |
  |   - TelemetryForwarder thread (KLV -> UDP)  |
  |   - VideoForwarder thread (RTSP -> SRT)     |
  |   - emits heartbeat + state + telemetry     |
  |     over the IPC socket                     |
  +---------------------------------------------+
                 |
                 v
       SRT :8890  + KLV UDP :12345    (unchanged)
       + tee branch -> HLS for dashboard
```

Full design in [architecture/overview.md](architecture/overview.md). State transitions in [architecture/state-machine.md](architecture/state-machine.md). API contract in [architecture/api-contract.md](architecture/api-contract.md).

## Success criteria

1. Power-cycle the drone mid-stream. Dashboard shows `degraded` for a few seconds, then `streaming` again, without any human action. SRT consumer sees a brief freeze but no process restart.
2. Unplug the Skycontroller USB for 30 seconds and plug it back in. Same result.
3. Kill `-9` the forwarder subprocess. Supervisor restarts it within 5 seconds.
4. Open `http://localhost:8080` on the host, `http://<machine-ip>:8080` on the LAN, or the host's VPN/Tailscale IP. See truthful connection state, telemetry validity, gimbal/camera data, and a "Reset" button that works.
5. `pytest` passes end-to-end on a machine with no drone connected. `pytest -m live` passes on a machine with a drone.
6. Fresh Ubuntu 24.04 ARM64 host -> `./scripts/install.sh` + `systemctl start parrot_forwarder`, or `docker compose up -d --build` -> dashboard reachable on the host IP/Tailscale IP - all in under 15 minutes with no manual steps.

## Out of scope / deferred to v3

- Cloud streaming targets (WebRTC relay, RTMP push).
- Multi-drone orchestration.
- Authenticated remote access (VPN gives us that today).
- Recording to disk (requires storage policy; v1 didn't have it either).
- Replacing Olympe (there is no alternative today).
