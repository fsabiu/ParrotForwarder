# Spec: REST API

See [../architecture/api-contract.md](../architecture/api-contract.md) for the definitive contract. This spec captures implementation requirements.

## Framework

FastAPI + uvicorn, single-worker, loopback bind.

## Router layout

```
routes/
  health.py     # GET /health
  status.py     # GET /status, GET /config
  control.py    # POST /control/{start,stop,reset}
  metrics.py    # GET /metrics (prometheus_client ASGI mount)
  stream.py     # WS /stream/events, /stream/telemetry
  preview.py    # GET /preview/* (static HLS)
```

## Error handling

- All endpoints return `application/problem+json` on error (RFC 7807).
- State-invalid errors return 409 with `problem.type = "state-invalid"` and the current state.
- Validation errors return 400 with `problem.detail` from pydantic.
- Log every 5xx at ERROR with the request ID.

## Request IDs

Every request is assigned a `X-Request-ID` (accepting one from the client if provided). Logged on all lines for that request. Returned in the response header.

## Rate limits

No global rate limit in v2 (localhost only). WebSocket telemetry stream is rate-limited server-side to the configured Hz to protect slow clients.

## Testing

- Use `TestClient` with a stub supervisor that replays canned state machine transitions.
- Separate integration test that spawns a real supervisor against mock drone and hits every endpoint with `curl`/`httpx`.
