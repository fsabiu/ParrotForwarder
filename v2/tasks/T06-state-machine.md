# T06 - Supervisor state machine

**Phase**: 1
**Depends on**: T04
**Estimated effort**: M

## Goal

Pure state machine per [../architecture/state-machine.md](../architecture/state-machine.md). No IO, no subprocess handling - just `(state, event) -> (new_state, side_effect_descriptors)`.

## Acceptance criteria

- `src/parrot_forwarder/state_machine.py` with `State` enum, `Event` dataclasses, `StateMachine` class.
- `step(event) -> List[SideEffect]` where `SideEffect` is a typed descriptor (`SpawnForwarder`, `KillForwarder`, `Log`, `EmitMetric`, `ScheduleRestart`, etc.).
- Backoff computation is a pure function, seedable RNG for tests.
- 100% transition coverage in tests, including every timeout and every illegal event (which should log + stay in state, not crash).

## Files touched

- `src/parrot_forwarder/state_machine.py`
- `src/parrot_forwarder/backoff.py`
- `tests/test_state_machine.py`
- `tests/test_backoff.py`

## How to verify

```bash
pytest tests/test_state_machine.py tests/test_backoff.py -v
```

## Notes

- No asyncio here. This module must work inside or outside an event loop.
- Side effects are descriptors only. The dispatcher in T07 executes them.
