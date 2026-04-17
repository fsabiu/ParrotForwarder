# T03 - Mock drone backend

**Phase**: 0
**Depends on**: T01
**Estimated effort**: M

## Goal

A mock that stands in for Olympe in unit and integration tests. Good enough to drive the state machine and the forwarder's control flow - does not need to emit real video.

## Acceptance criteria

- `src/parrot_forwarder/testing/mock_drone.py` exposes a `MockDrone` class matching the subset of `olympe.Drone` API used by the codebase (`connect`, `disconnect`, `get_state`, event subscribe).
- `MockDrone` is controllable from tests: set battery, GPS fix, force a disconnect, raise on next `get_state`, etc.
- `MockDrone` default behavior: connects successfully after 100 ms, emits battery 75% / GPS fix true / yaw 0, stays happy until test asks otherwise.
- No changes to production code - tests can swap Olympe via DI (pass `drone_factory=MockDrone` to the forwarder, default `olympe.Drone`).

## Files touched

- `src/parrot_forwarder/testing/__init__.py`
- `src/parrot_forwarder/testing/mock_drone.py`
- `src/parrot_forwarder/main.py` (add `drone_factory` param with default)
- `tests/test_mock_drone.py`

## How to verify

```bash
pytest tests/test_mock_drone.py -v
```

## Notes

- Start by enumerating the Olympe methods actually called in v1: `connect`, `disconnect`, `get_state(BatteryStateChanged)`, subscribe for telemetry. That's the surface to mock - nothing more.
- Do not try to mock GStreamer here. That's T11.
