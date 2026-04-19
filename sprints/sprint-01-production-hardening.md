# Sprint 1 - ParrotForwarder production hardening

## Status

- Started: 2026-04-19
- Completed: 13 / 34 implementation tasks (Phase 1 complete)
- Last updated: 2026-04-19
- Owner: Francesco
- Related plan file: `~/.claude/plans/twinkling-sniffing-tarjan.md` (archival design doc)

### Progress log

- 2026-04-19 Phase 1 landed: bind mount to `ParrotForwarder/recordings/`, non-root container user, ffmpeg+iproute2 in image, config-dir bind mount via entrypoint seed, `RecordingConfig`, SQLite index, Recorder (ffmpeg with `-map 0:v -map 0:d -c copy`), crash recovery, recording API + dashboard panel. New tests: 47 passing (config, index, recorder, api). Full suite: 195 pass, 3 pre-existing HLS-related failures in `test_dashboard.py` (unrelated to sprint 1, carryover from MJPEG migration).

## Goal

Make ParrotForwarder v2 deployable to production with a single rule: **operators do everything from the dashboard**. No SSH, no `docker exec`, no terminal commands after `docker compose up`. The detector (`real-time-object-detection`) must keep consuming SRT on `:8890` with no change.

## Acceptance criteria for the whole sprint

- Fresh clone + `docker compose up -d` produces a running dashboard at `http://127.0.0.1:8080`.
- Operator can: start/stop forwarding, start/stop recording, change any config field, see SRT status, see all telemetry, verify gimbal orientation visually - all from the dashboard.
- Recordings land in `ParrotForwarder/recordings/` on the host, visible in macOS Finder, ownable/deletable without `sudo`.
- Every recording `.ts` contains both video (H.264) and data (KLV) streams. `ffprobe` confirms.
- Detector continues to pull SRT from the forwarder with no regression.
- Container restarts cleanly on SIGTERM without corrupting recordings or losing config changes.

## Recording command (reference)

Validated manually by Francesco:

```
ffmpeg -i 'srt://100.105.188.84:8890' -map 0:v -map 0:d -c copy -t 10 test_with_klv.ts
```

Production form used by the supervisor's Recording subprocess:

```
ffmpeg -hide_banner -nostdin -y \
  -i 'srt://127.0.0.1:8890?mode=caller' \
  -map 0:v -map 0:d -c copy \
  -f mpegts <out>.ts
```

Clean stop: send SIGINT so ffmpeg flushes the muxer and writes a valid trailer.

---

## Phase 1 - Foundation (bind mount + recording)

### Docker + bind mount

- [x] **T1.1** Add `./recordings:/recordings` bind mount to `docker-compose.yml`
  - Files: `docker-compose.yml` (also bound `./config:/etc/parrot-forwarder` as directory mount; entrypoint seeds YAML from `config.yaml.example` on first boot)
  - DoD: compose YAML valid (`python yaml.safe_load` check); `./recordings/` and `./config/` auto-created on host

- [x] **T1.2** Add non-root user to Dockerfile and pre-own volume paths
  - Files: `Dockerfile`, `scripts/docker-entrypoint.sh`
  - `useradd --uid 1000 parrot`; pre-owns `/recordings`, `/var/log/parrot-forwarder`, `/etc/parrot-forwarder`; `USER parrot`
  - DoD: image rebuild required to verify at runtime; confirmed in Dockerfile

- [x] **T1.3** Install ffmpeg + iproute2 in the image
  - Files: `Dockerfile`
  - DoD: packages added to apt-get install list

- [x] **T1.4** Add `stop_grace_period: 30s` and `.gitignore` entry for `recordings/`
  - Files: `docker-compose.yml`, `.gitignore`
  - DoD: stop_grace_period 30s set; `.gitignore` ignores `recordings/` and `config/parrot-forwarder.yaml` while keeping `.gitkeep`

### Recording config + data model

- [x] **T1.5** Add `RecordingConfig` dataclass to `config.py`
  - DoD met. `GET /config` not yet exposing (that's Phase 3 T3.1); default-value tests pass.

- [x] **T1.6** Create SQLite index module
  - DoD met. 10 unit tests pass covering CRUD + crash-reopen + filters + disk usage.

- [x] **T1.7** Create Recorder class managing the ffmpeg subprocess
  - DoD met. 9 unit tests pass using a mock-ffmpeg shell script (POSIX-safe). Real-ffmpeg SRT integration is covered by manual test T4.5 once the container is running with the drone.

- [x] **T1.8** Crash recovery on supervisor startup
  - Covered by `reconcile_active_rows()` in `recorder.py` and `test_reconcile_*` tests. Wired into CLI boot sequence.

### Recording API

- [x] **T1.9** `POST /recording/start` endpoint
  - Files: `src/parrot_forwarder/supervisor/api/recording.py`, `supervisor/api/__init__.py` (router wired), `supervisor/cli.py` (recorder lifecycle)
  - DoD met: 201 Created returns `{recording_id, path, started_at, ...}`; 409 on double-start; 503 on ffmpeg failure.

- [x] **T1.10** `POST /recording/stop` endpoint
  - DoD met: sidecar finalized, index row state='finalized', response includes duration, bytes, sha256.

- [x] **T1.11** `GET /recording/status`, `/recording/list`, `/recording/{id}/metadata`, `/recording/{id}/download`, `DELETE /recording/{id}`, `GET /recording/disk`
  - DoD met via 6 integration tests. Delete moves file + sidecar to `.trash/<id>/`. List defaults exclude deleted (opt-in via `include_deleted=true`).

### Dashboard - Recording UI

- [x] **T1.12** Add Recording panel to `dashboard/static/index.html`
  - DoD met: Start/Stop buttons, REC indicator (pulsing red when active), elapsed counter, live byte count, mission + drone + notes inputs persisted in localStorage.

- [x] **T1.13** Add Recordings table + Disk widget
  - DoD met: table with Start, Duration, Size, Mission, Download, Delete; disk widget with progress bar of used/total + free/count readout; WebSocket `recording.started|stopped|error` events trigger automatic refresh.

---

## Phase 2 - Observability (SRT status + full telemetry + gimbal)

### SRT output status

- [ ] **T2.1** Implement `SrtStatusMonitor` class
  - Files: `src/parrot_forwarder/srt_status.py` (new)
  - Poll every 1 s: run `ss -Htn state established "sport = :<srt_port>"` (or equivalent for UDP-wrapped SRT, verify at implementation - may need `ss -Htu` depending on srtsink build), parse lines for peer addresses
  - Poll GStreamer `srtsink` properties `bytes-sent-total` / `packets-sent-total` via the running pipeline's element ref
  - Compute `bitrate_bps` as moving average over the last 5 s of bytes-sent
  - State machine: `listening` (no clients) / `streaming` (>=1 client, bytes flowing) / `stalled` (clients but no bytes for 3 s)
  - DoD: unit test with mocked `ss` output; lint passes

- [ ] **T2.2** `GET /srt/status` endpoint
  - Returns: `{state, port, client_count, clients: [{ip, port, since?}], bytes_out_total, bitrate_bps, last_client_event}`
  - DoD: with ffmpeg consuming the stream from host, returns `streaming` with 1 client; after disconnect, returns `listening` with 0 clients within 2 s

- [ ] **T2.3** SRT card in dashboard
  - Traffic-light indicator (gray / green / red), client count badge, collapsible client list, rolling bitrate chart (simple sparkline, last 60 s)
  - DoD: observed live when the detector container connects; stays accurate during pipeline restart

### Telemetry completeness

- [ ] **T2.4** Subscribe to missing Olympe events
  - Files: `src/parrot_forwarder/telemetry.py`
  - Events to add (in priority order): `WifiRssiChanged`, `NumberOfSatellitesChanged`, `FlyingStateChanged` (full enum), `AlertStateChanged`, `ReturnHomeState` + `HomeTypeChosenChanged`, `MagnetoCalibrationRequiredState`, `MassStorageInfo` + `MassStorageStateChanged`, `AltitudeAboveGroundChanged`, `SpeedChanged` (vx, vy, vz), `ControllerStateChanged`
  - DoD: each field shows up in `GET /telemetry/snapshot` (existing) with sensible values at idle; unit tests with mocked Olympe events

- [ ] **T2.5** Extend dashboard telemetry grid, grouped by domain
  - Groups: Drone, Controller, GPS, Flight, Camera, Gimbal, Storage, Network
  - DoD: 60+ fields visible, grouped, each field shows `-` when null rather than missing

- [ ] **T2.6** Staleness indicator per telemetry group
  - Each group header shows `Xs ago` based on last update timestamp; red if >5 s
  - DoD: disconnect drone -> timestamps freeze and turn red; reconnect -> they turn green and update

### Gimbal correctness

- [ ] **T2.7** Sign-convention + units banner in dashboard gimbal panel
  - Hardcoded text: `Yaw: 0=mag-N, +CW. Pitch: 0=horizon, + up, - down. Roll: + right-side-down. Units: degrees.`
  - Implementation task: verify against Olympe docs + physical test at T3 testing. If wrong, correct at source in `telemetry.py` and update banner
  - DoD: banner present; T3-Gimbal test passes

- [ ] **T2.8** Frame-of-reference change event
  - Files: `src/parrot_forwarder/telemetry.py`
  - Whenever any of `gimbal_{yaw,pitch,roll}_frame_of_reference` changes, emit an event to `/stream/events` with before/after values
  - DoD: toggling gimbal mode on Skycontroller produces a dashboard event line

- [ ] **T2.9** KLV encoder guard for ABS tags
  - Files: `src/parrot_forwarder/klv_encoder.py`
  - If any axis frame-of-reference is `RELATIVE_FRAME`, do NOT emit KLV 105/106/107 for that axis (avoids misleading downstream consumers)
  - Log a `warning` event once per transition, not per frame
  - DoD: unit test covers both states

- [ ] **T2.10** Visual gimbal orientation widget
  - Files: `dashboard/static/app.js`, `dashboard/static/style.css`
  - Small SVG: top-down compass showing drone heading (arrow) + camera yaw (cone), side view showing camera pitch vs horizon
  - Side-by-side numeric block: ABS triple vs REL triple, each labeled with its frame-of-reference
  - DoD: rotating the drone rotates the compass arrow; tilting gimbal tilts the side view; T3-Gimbal test passes

- [ ] **T2.11** Raw telemetry debug view
  - Dashboard has a collapsible "Raw Olympe" panel showing the untransformed dict; below it a "Encoded KLV (decoded)" panel showing what the KLV muxer writes, with tag numbers
  - Enables byte-level verification against a `.ts` capture in `ffprobe`
  - DoD: values in both panels match after a conversion round-trip

### Pre-flight strip

- [ ] **T2.12** `GET /ready` endpoint
  - Returns: `{drone: {connected, last_telemetry_ms_ago}, srt: {state, client_count}, recording: {active, disk_free_bytes}, preview: {active_clients}}`
  - Keep `GET /health` as pure liveness (for Docker healthcheck)
  - DoD: returns full JSON; 200 when drone connected, 503 when not (for monitoring integration)

- [ ] **T2.13** Dashboard pre-flight traffic-light strip
  - Top-of-page row: Drone / GPS / SD / Link / SRT / Recording, each green/yellow/red/gray
  - DoD: strip reflects real-time state; clicking a segment scrolls to the relevant details panel

---

## Phase 3 - Control plane (config via dashboard + auth)

- [ ] **T3.1** Expand `GET /config` to return the full live config
  - Files: `src/parrot_forwarder/supervisor/api/__init__.py`
  - Redact secrets (the new `supervisor.auth.api_key` gets masked)
  - DoD: response matches `Config` dataclass shape

- [ ] **T3.2** `PUT /config` endpoint
  - Accepts full config document; validates via pydantic; classifies each change as reloadable/restart-required
  - Persists to the mounted YAML file atomically (write to `.tmp`, `fsync`, rename)
  - Applies reloadable changes immediately via existing `reload_config` (`config.py:285-325`)
  - Returns `{applied: [paths], staged: [paths], requires_restart: bool}`
  - DoD: editing `forwarder.telemetry_fps` applies immediately; editing `drone.ip` stages and requires restart

- [ ] **T3.3** Settings page in dashboard
  - Files: `dashboard/static/index.html`, `dashboard/static/app.js`
  - Tabs per section (Drone, Forwarder, Supervisor, Logging, Preview, Metrics, Recording)
  - Lock icon on restart-required fields
  - "Save" button; if any restart-required field changed, modal offers "Apply and restart now" (calls `POST /control/reset`) vs "Save and restart later"
  - DoD: all fields editable; invalid values rejected inline with the pydantic error; YAML file on disk reflects saves

- [ ] **T3.4** API key middleware
  - Files: `src/parrot_forwarder/supervisor/api/auth.py` (new)
  - Gates write endpoints only: `POST /control/*`, `PUT /config`, `POST /recording/*`, `DELETE /recording/*`
  - Key from `supervisor.auth.api_key` config field; header `X-API-Key`
  - On first boot if key is empty, auto-generate and write to YAML; surface once in dashboard with rotate button
  - DoD: write without key -> 401; with key -> 200; rotate key from dashboard invalidates old key

---

## Phase 4 - Nice-to-have (do not block sprint completion)

- [ ] **T4.1** Auto-on-takeoff recording trigger (honors `recording.auto_on_takeoff`)
- [ ] **T4.2** Diagnostics bundle endpoint: `GET /diagnostics` returns a ZIP (redacted logs + config + index.db + `/ready` snapshot)
- [ ] **T4.3** Event log filter/search in dashboard
- [ ] **T4.4** Retention job: nightly cron inside supervisor enforcing `recording.retention_days`

---

## Testing plan (dashboard-only, drone required for T3 group)

No terminal commands after `docker compose up`. All checks observed from dashboard at `http://127.0.0.1:8080`.

### T0 - No drone required

- [ ] **T0.1** Fresh clone -> `UID=$(id -u) GID=$(id -g) docker compose up -d` -> dashboard loads, healthcheck green within 20 s
- [ ] **T0.2** Settings page: edit `forwarder.telemetry_fps` 2->5, applies without restart; edit `drone.ip`, restart prompt appears, apply-and-restart succeeds
- [ ] **T0.3** Write endpoints require API key; rotate key from dashboard works
- [ ] **T0.4** `docker compose down` with supervisor running -> container exits cleanly within 30 s
- [ ] **T0.5** Kill container mid-(mock)-recording -> restart -> orphan `active` index row reconciles to `finalized` or `error`

### T1 - Link + telemetry (drone on)

- [ ] **T1.1** Connect Skycontroller + Anafi. Pre-flight strip all green within 10 s
- [ ] **T1.2** Telemetry page shows 60+ fields, all groups populated, none older than 2 s
- [ ] **T1.3** Disconnect drone -> strip turns red; reconnect -> green

### T2 - SRT status

- [ ] **T2.1** Dashboard SRT card shows `listening, 0 clients, 0 B/s` before anything connects
- [ ] **T2.2** Start detector (or run `ffplay srt://127.0.0.1:8890?mode=caller` from another terminal) -> card shows `streaming, 1 client, <ip>, ~2-5 Mbps` within 2 s
- [ ] **T2.3** Disconnect client -> card drops to `listening, 0 clients`
- [ ] **T2.4** Detector consumes the SRT stream and produces detections as before (regression check)

### T3 - Gimbal correctness

- [ ] **T3.1** Level drone, camera at horizon: ABS pitch ~0, ABS roll ~0. Orientation widget matches
- [ ] **T3.2** Rotate drone 90 deg CW (nose east from nose north): ABS yaw advances ~90 deg, REL yaw stays ~0
- [ ] **T3.3** Tilt gimbal straight down: ABS pitch ~-90, REL pitch ~-90 (independent of drone heading)
- [ ] **T3.4** Toggle gimbal mode on Skycontroller: dashboard event log shows frame-of-reference change; if any axis flips to relative, ABS tag for that axis stops updating in debug view
- [ ] **T3.5** Sign-convention banner matches observed behavior; if not, file a follow-up to fix in `telemetry.py` (do not close sprint until matched)

### T4 - Recording

- [ ] **T4.1** Click Start on dashboard: live counter runs, file path shows under `recordings/YYYY-MM-DD/...`
- [ ] **T4.2** Open macOS Finder at `ParrotForwarder/recordings/`: folder hierarchy visible, `.ts` file is growing
- [ ] **T4.3** Fly ~60 s; click Stop; dashboard row appears in Recordings table with duration, size, SHA256
- [ ] **T4.4** Double-click `.ts` in Finder: QuickTime plays video
- [ ] **T4.5** Open recording in a terminal `ffprobe <file>.ts` -> output shows BOTH a `video: h264` stream AND a `data: klvmeta` (or `bin_data`) stream. **Explicit Francesco requirement: video AND telemetry must both be present.**
- [ ] **T4.6** Delete from dashboard: row removed, file moved to `recordings/.trash/<id>/` (visible in Finder)

### T5 - Disk + retention

- [ ] **T5.1** Disk widget reflects actual free space (`df -h` matches within 1 GB)
- [ ] **T5.2** Set `recording.max_bytes_per_file` to 100 MB, record until threshold. Recorder rolls over to a new file or stops gracefully (document which behavior; recommend stop + event + refuse-new-recording-until-disk-action)

---

## Explicit non-goals for sprint 1

- No Oracle / COP ingestion.
- No multi-drone support.
- No WebRTC preview upgrade.
- No TLS by default (API key only; Caddy TLS is a followup).
- No changes to `real-time-object-detection/`.

## Risks + mitigations

- **Olympe event names may vary by drone firmware**: gate each new subscription behind a try/except; log "event not available" and continue rather than failing the worker.
- **`ss` output format differs across distros**: stick to the `ubuntu:24.04` base in Dockerfile; unit-test the parser with the exact format captured at build time.
- **Apple Silicon + Docker Desktop bind mount permissions**: explicitly pass `UID`/`GID` at compose up. Wrapper script `run.sh` can export them to reduce operator error.
- **Gimbal sign-convention**: the T3 testing group is the ground truth. If Olympe's reported signs disagree with the banner, the fix is in `telemetry.py` (flip sign before storing), not in the banner. Capture the verdict in an ADR.
