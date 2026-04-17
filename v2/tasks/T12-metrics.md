# T12 - Prometheus metrics

**Phase**: 2
**Depends on**: T06, T10
**Estimated effort**: S

## Goal

Expose metrics listed in [../architecture/state-machine.md#metrics-exported](../architecture/state-machine.md#metrics-exported) plus pipeline metrics (FPS, bitrate).

## Acceptance criteria

- `prometheus_client` ASGI app mounted at `/metrics`.
- All metrics declared with consistent names (`parrot_forwarder_*` prefix) and help strings.
- State transitions and restarts increment counters in the state machine dispatcher, not scattered through the code.
- `curl /metrics` parses cleanly with `promtool check metrics`.

## Files touched

- `src/parrot_forwarder/metrics.py`
- `tests/test_metrics.py`

## How to verify

```bash
curl -s http://localhost:8080/metrics | promtool check metrics
```
