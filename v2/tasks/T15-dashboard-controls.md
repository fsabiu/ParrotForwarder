# T15 - Dashboard controls and event log

**Phase**: 3
**Depends on**: T13, T11

**Estimated effort**: S

## Goal

Wire Start / Stop / Reset buttons and the event log to the supervisor.

## Acceptance criteria

- Buttons call `/control/start|stop|reset`; disabled when current state doesn't allow the action.
- Reset prompts `window.confirm` before firing.
- Event log tails `/stream/events`, newest on top, cap 200 entries, auto-scrolls only when user is at top.
- Visual disable during in-flight request.

## Files touched

- `dashboard/src/components/Controls.*`
- `dashboard/src/components/EventLog.*`

## How to verify

Manually click through each combination; run Playwright smoke from [../specs/04-dashboard.md](../specs/04-dashboard.md).
