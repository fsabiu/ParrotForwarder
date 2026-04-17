# T09 - Structured JSON logging

**Phase**: 1
**Depends on**: T01, T02
**Estimated effort**: S

## Goal

Replace v1's `logging.basicConfig` text format with structured JSON to file (rotating) plus stdout, and per-module log levels.

## Acceptance criteria

- `src/parrot_forwarder/logging_setup.py` exposes `configure_logging(config: LoggingConfig)`.
- JSON formatter outputs: `ts` (ISO-8601 UTC), `level`, `logger`, `msg`, plus any `extra` fields.
- Rotating file handler honors `max_bytes` and `backup_count` from config.
- Every state transition, restart, and API request logs at INFO with structured fields (`event`, `from`, `to`, `reason`, `request_id`).
- Olympe and ulog loggers default to WARNING; overridable via config.

## Files touched

- `src/parrot_forwarder/logging_setup.py`
- `tests/test_logging.py`

## How to verify

Run supervisor against mock drone; tail the log file; confirm JSON parseable with `jq`.

## Notes

- Use stdlib `logging` + a small formatter. No third-party logger (structlog) unless a strong reason emerges.
