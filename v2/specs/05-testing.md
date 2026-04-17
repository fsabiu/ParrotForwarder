# Spec: Testing Strategy

Three tiers. No live drone required for the first two.

## Tier 1 - Unit

pytest, no IO beyond in-memory fixtures.

Coverage targets:

- `state_machine.py` - 100% of transitions, including error paths.
- `config.py` - all precedence rules, validation, reload.
- `klv_encoder.py` - regression tests with golden binary fixtures (preserve v1 output bit-for-bit).
- `ipc.py` - frame encode/decode, back-pressure handling.
- `backoff.py` - deterministic with seeded RNG.

## Tier 2 - Integration (mock drone, mock GStreamer)

pytest with async fixtures. Spawns a real supervisor process against a mock forwarder.

Scenarios:

- Happy path: supervisor starts, forwarder reports olympe.connected + pipeline.started, supervisor reaches STREAMING, `/status` reflects it.
- Forwarder crash: kill the mock forwarder mid-stream, assert RESTARTING -> CONNECTING -> STREAMING within backoff window.
- Pipeline error: mock emits `pipeline.error`, assert restart.
- Olympe disconnect: mock emits `olympe.disconnected`, assert restart.
- Heartbeat timeout: mock stops sending heartbeats, assert DEGRADED then RESTARTING.
- Reset via API: `POST /control/reset` during STREAMING, assert restart cycle.
- Stop via API: `POST /control/stop` stops and does not auto-restart.
- Config reload: SIGHUP with valid change takes effect; with invalid, old config stays.

## Tier 3 - End-to-end (real pipeline, no drone)

An in-process SRT receiver fixture + a mock Olympe that emits synthetic camera frames through GStreamer's `videotestsrc`.

- Start supervisor -> connect receiver to SRT port -> assert at least 30 frames received within 10 s.
- KLV presence: decode muxed packets, assert at least one KLV packet per second has correct MISB 0601 sync bytes.

## Live tier (documented, not automated)

A checklist for smoke-testing against real hardware before release. Run manually on an LTS-certified host.

- Cold boot: fresh install -> dashboard reachable in 15 s.
- Power cycle drone mid-stream: dashboard shows brief red, recovers.
- USB unplug/replug: same.
- 24 h soak: uptime clean, no memory growth >10%.
- kill -9 forwarder subprocess: restart in <5 s.

## Markers

- `@pytest.mark.live` - requires real drone. Skipped in CI. Run on hardware host with `pytest -m live`.
- `@pytest.mark.slow` - > 30 s, run with `pytest -m slow` or excluded from quick loop.

## CI

- GitHub Actions on push and PR.
- Matrix: Ubuntu 24.04 runner, Python 3.11.
- Steps: install deps from `requirements-dev.txt`, lint (`ruff`), type-check (`mypy`), pytest (exclude `live` and `slow`), build dashboard.
- No coverage gate in v2 (premature). Track coverage, don't enforce.

## Fixtures

- `mock_drone`: implements the Olympe surface we use (connect, disconnect, state subscribe). In `parrot_forwarder/testing/mock_drone.py`, exported so downstream projects can reuse.
- `mock_forwarder`: a tiny Python script that emits canned IPC events, used by Tier 2.
- `srt_receiver`: async context manager that opens an SRT listener, yields frames and KLV packets.

## Flakiness policy

- Any test that fails intermittently in CI three times in a week is either fixed or deleted. No silent retries in CI config.
