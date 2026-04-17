# T16 - Integration test harness

**Phase**: 4
**Depends on**: T07, T10, T11

**Estimated effort**: M

## Goal

Tier-2 tests from [../specs/05-testing.md](../specs/05-testing.md) running in CI.

## Acceptance criteria

- `tests/integration/` holds test modules.
- Shared `Supervisor` fixture that spawns the real supervisor against a mock forwarder; teardown is reliable.
- Scenarios implemented: happy path, forwarder crash, pipeline error, olympe disconnect, heartbeat timeout, reset, stop, config reload.
- CI runs them on every PR.

## Files touched

- `tests/integration/` (new)
- `.github/workflows/ci.yml` (add step if needed)
