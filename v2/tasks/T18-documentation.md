# T18 - Operator runbook and dev guide

**Phase**: 4
**Depends on**: T05, T10

**Estimated effort**: M

## Goal

Documentation sufficient to run and extend v2 without reading the source.

## Acceptance criteria

- `docs/runbook.md`: install, start, stop, reload config, rollback to v1, common troubleshooting (pipeline stuck, drone not found, dashboard blank).
- `docs/dev-guide.md`: architecture tour, how to add a metric, how to add a state-machine event, how to test without hardware.
- `docs/openapi.yaml`: auto-generated from FastAPI, committed.
- Top-level `README.md` rewritten to point at v2 docs; install section collapses to install.sh.

## Files touched

- `docs/` (new)
- `README.md`
