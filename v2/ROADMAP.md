# v2 Roadmap

Five phases. Each phase is shippable on its own - at any phase boundary, the service works and is better than v1. Do not skip phases.

## Phase 0 - Foundation (no code changes to runtime behavior)

Goal: the project can be developed and tested without hardware.

- Reorganize package layout under `src/parrot_forwarder/`.
- Pyproject + console script entry point.
- `scripts/install.sh` that replaces the README copy-paste.
- Mock Olympe backend (`parrot_forwarder.testing.mock_drone`) good enough for unit tests.
- pytest skeleton with `live` marker; CI (GitHub Actions) running non-live tests.
- ADRs for supervisor architecture and backend framework choice.

**Exit criteria**: `pytest` passes on CI with zero hardware; existing v1 behavior still runs when invoked as a CLI.

## Phase 1 - Supervisor and config

Goal: the runtime is autonomous.

- Config loader (`config.yaml` with CLI overrides).
- Supervisor process that spawns the forwarder subprocess over Unix socket IPC.
- Explicit state machine (`DISCONNECTED -> CONNECTING -> READY -> STREAMING -> DEGRADED -> RESTARTING`).
- Health monitor covering both Olympe connection and GStreamer pipeline.
- Exponential backoff with jitter on restart; structured reason codes for each restart.
- Structured JSON logging with rotation.

**Exit criteria**: the three chaos tests in [PLAN.md#success-criteria](PLAN.md#success-criteria) items 1, 2, 3 pass without any manual intervention.

## Phase 2 - REST API and telemetry stream

Goal: external integrations have a contract.

- FastAPI app mounted on supervisor.
- `GET /health`, `GET /status`, `GET /config`.
- `POST /control/start`, `/control/stop`, `/control/reset`.
- WebSocket `/stream/events` (state transitions, errors, restarts).
- WebSocket `/stream/telemetry` (10 Hz KLV-equivalent JSON).
- Prometheus `/metrics`.
- OpenAPI spec auto-generated and committed to `docs/openapi.yaml`.

**Exit criteria**: `curl` hits all endpoints on localhost and gets sensible responses while the drone is streaming.

## Phase 3 - Dashboard

Goal: operator has a single pane of glass.

- Static SPA served from supervisor at `/`.
- Live connection state, battery, GPS fix, uptime, restart count.
- Event log (last N events, streamed via WS).
- Video preview (HLS or WebRTC - decided in [ADR-004](decisions/ADR-004-video-preview-transport.md)).
- Start / Stop / Reset buttons wired to REST.
- Telemetry gauges (altitude, speed, attitude).

**Exit criteria**: opening `http://localhost:8080` on a fresh host shows a working dashboard against a live drone within 15 seconds of page load.

## Phase 4 - Tests, docs, packaging

Goal: someone else can run and extend this.

- Integration tests against mock drone (full supervisor lifecycle).
- E2E smoke test using an in-process SRT receiver fixture.
- Live test matrix (documented, not automated): power cycle, USB pull, controller reboot, long-soak 24 h.
- Operator runbook: install, upgrade, rollback, troubleshoot.
- Dev guide: architecture tour, how to add a new metric, how to extend state machine.
- API reference from OpenAPI.
- Dockerfile with USB passthrough documented.
- GitHub release + tagged v2.0.0.

**Exit criteria**: a new developer can open the repo, read `README.md`, and have a running dashboard against mock drone within 10 minutes on their laptop.
