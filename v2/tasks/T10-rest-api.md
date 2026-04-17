# T10 - REST API

**Phase**: 2
**Depends on**: T07
**Estimated effort**: M

## Goal

Expose the supervisor over HTTP per [../architecture/api-contract.md](../architecture/api-contract.md) and [../specs/03-rest-api.md](../specs/03-rest-api.md).

## Acceptance criteria

- FastAPI app in `src/parrot_forwarder/supervisor/api/` with routes split per [../specs/03-rest-api.md](../specs/03-rest-api.md).
- Bound to `127.0.0.1` by default; binding to anything else requires explicit config.
- `GET /health`, `GET /status`, `GET /config`, `POST /control/{start,stop,reset}` all pass integration tests.
- Error responses use `application/problem+json`.
- Request ID middleware in place.

## Files touched

- `src/parrot_forwarder/supervisor/api/` (new subpackage, per-route files)
- `tests/test_api.py`

## How to verify

```bash
parrot-forwarder &
curl -sf http://localhost:8080/health
curl -sf http://localhost:8080/status | jq
```

## Notes

- uvicorn in-process (not as separate process). Supervisor orchestrates lifecycle.
